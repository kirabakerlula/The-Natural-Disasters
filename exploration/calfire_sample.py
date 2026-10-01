import requests
import pandas as pd


url = "https://incidents.fire.ca.gov/umbraco/Api/IncidentApi/GetIncidents"

params = {
    "year": 2025
}

response = requests.get(url, params=params)

print("Status code:", response.status_code)

data = response.json()

incidents = data["Incidents"]

rows = []

for incident in incidents:
    rows.append({
        "fire_id": incident["UniqueId"],
        "name": incident["Name"],
        "started": incident["Started"],
        "location": incident["Location"],
        "counties": incident["Counties"],
        "county_ids": incident["CountyIds"],
        "latitude": incident["Latitude"],
        "longitude": incident["Longitude"],
        "acres_burned": incident["AcresBurned"],
        "percent_contained": incident["PercentContained"],
        "structures_destroyed": incident["StructuresDestroyed"]
    })

df = pd.DataFrame(rows)

df["started"] = pd.to_datetime(
    df["started"],
    utc=True
)

df["date"] = df["started"].dt.date
df["year_month"] = df["started"].dt.strftime("%Y-%m")

print("\nFirst 5 rows:")
print(df.head())

print("\nNumber of rows and columns:")
print(df.shape)

print("\nColumns:")
print(df.columns.tolist())

print("\nMissing values:")
print(df.isna().sum())

selected_columns = [
    "fire_id",
    "date",
    "year_month",
    "name",
    "counties",
    "county_ids",
    "latitude",
    "longitude",
    "acres_burned",
    "percent_contained"
]

sample_df = df[selected_columns]

print("\nSelected columns:")
print(sample_df.head())

sample_df.to_csv(
    "calfire_wildfire_sample.csv",
    index=False
)

print("\nSaved sample data to calfire_wildfire_sample.csv")
