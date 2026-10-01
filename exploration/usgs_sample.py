import requests
import pandas as pd


# USGS Earthquake API
url = "https://earthquake.usgs.gov/fdsnws/event/1/query"

# Request earthquakes around California from 2016 to 2026
params = {
    "format": "geojson",
    "starttime": "2016-01-01",
    "endtime": "2026-10-01",
    "minmagnitude": 4.0,

    # Approximate California bounding box
    "minlatitude": 32.5,
    "maxlatitude": 42.0,
    "minlongitude": -124.5,
    "maxlongitude": -114.1,
}


# Call the USGS API
response = requests.get(url, params=params)

print("Status code:", response.status_code)

data = response.json()


# Extract useful fields from the API response
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


# Convert API results into a DataFrame
df = pd.DataFrame(rows)

print("\nRecords before California place filter:", len(df))


# Keep only earthquakes whose USGS place description contains ", CA"
df = df[
    df["place"].str.contains(", CA", na=False)
].copy()

print("Records after California place filter:", len(df))


# Convert timestamp into readable datetime
df["time"] = pd.to_datetime(
    df["time"],
    unit="ms",
    utc=True
)


# Add date and year-month columns
df["date"] = df["time"].dt.date
df["year_month"] = df["time"].dt.strftime("%Y-%m")


# Show basic information about the data
print("\nFirst 5 rows:")
print(df.head())

print("\nNumber of rows and columns:")
print(df.shape)

print("\nColumns:")
print(df.columns.tolist())

print("\nMissing values:")
print(df.isna().sum())


# Keep the columns useful for the project
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

earthquake_df = df[selected_columns]


print("\nSelected columns:")
print(earthquake_df.head())


# Save the cleaned California earthquake data
earthquake_df.to_csv(
    "usgs_california_earthquakes_2016_2026.csv",
    index=False
)

print(
    "\nSaved data to usgs_california_earthquakes_2016_2026.csv"
)