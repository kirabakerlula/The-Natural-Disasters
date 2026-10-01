import requests
import pandas as pd


# CAL FIRE Incident API
url = "https://incidents.fire.ca.gov/umbraco/Api/IncidentApi/GetIncidents"

all_incidents = []


# Request CAL FIRE incidents from 2016 through 2026
for year in range(2016, 2027):

    params = {
        "year": year
    }

    response = requests.get(url, params=params)

    print(f"{year} status code:", response.status_code)

    if response.status_code == 200:
        data = response.json()

        incidents = data.get("Incidents", [])

        print(f"{year} incidents:", len(incidents))

        all_incidents.extend(incidents)

    else:
        print(f"Failed to retrieve data for {year}")


print("\nTotal incidents retrieved:", len(all_incidents))


# Extract useful fields
rows = []

for incident in all_incidents:
    rows.append({
        "fire_id": incident.get("UniqueId"),
        "name": incident.get("Name"),
        "started": incident.get("Started"),
        "location": incident.get("Location"),
        "counties": incident.get("Counties"),
        "county_ids": incident.get("CountyIds"),
        "latitude": incident.get("Latitude"),
        "longitude": incident.get("Longitude"),
        "acres_burned": incident.get("AcresBurned"),
        "percent_contained": incident.get("PercentContained"),
        "structures_destroyed": incident.get("StructuresDestroyed")
    })


# Convert results into a DataFrame
df = pd.DataFrame(rows)


# Convert started date into datetime
df["started"] = pd.to_datetime(
    df["started"],
    utc=True,
    errors="coerce"
)


# Keep only incidents from 2016 through October 1, 2026
df = df[
    (df["started"] >= "2016-01-01") &
    (df["started"] <= "2026-10-01 23:59:59+00:00")
].copy()


# Add date and year-month columns
df["date"] = df["started"].dt.date
df["year_month"] = df["started"].dt.strftime("%Y-%m")


# Remove duplicate incidents if the API returns any
df = df.drop_duplicates(
    subset=["fire_id"]
).copy()


# Show basic information
print("\nFirst 5 rows:")
print(df.head())

print("\nNumber of rows and columns:")
print(df.shape)

print("\nColumns:")
print(df.columns.tolist())

print("\nMissing values:")
print(df.isna().sum())


# Keep columns useful for the project
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

wildfire_df = df[selected_columns]


print("\nSelected columns:")
print(wildfire_df.head())


# Show number of fires by year
print("\nNumber of incidents by year:")
print(
    df["started"]
    .dt.year
    .value_counts()
    .sort_index()
)


# Save cleaned California wildfire data
wildfire_df.to_csv(
    "calfire_wildfires_2016_2026.csv",
    index=False
)

print(
    "\nSaved data to calfire_wildfires_2016_2026.csv"
)