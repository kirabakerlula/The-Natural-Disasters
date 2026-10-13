import json
import re

import os
from dotenv import load_dotenv

from google.oauth2 import service_account
from google.cloud import storage
import streamlit as st
import pandas as pd
import io

# get environment variables
load_dotenv()

# GCS related:
service_account_key = os.getenv("GCP_SERVICE_ACCOUNT_KEY")
project_id = os.getenv("GCP_PROJECT_ID")
bucket_name = os.getenv("GCS_BUCKET")

# Authenticate / get credentials
credentials = service_account.Credentials.from_service_account_file(
    service_account_key)

def pull_from_gcs(file_name):
    try:
        # set up GCP bucket
        client = storage.Client(project=project_id, credentials=credentials)
        bucket = client.bucket(bucket_name)
        file = bucket.blob(file_name)
        # pull data from bucket
        data = file.download_as_bytes()
    except Exception as e:
        print(f"Could not read {file_name} from {bucket_name}: {e}")
        raise
    return data


#"""
#IF: data is a csv_file:
#df = pd.read_csv(io.BytesIO(data))

#IF: data is json:
#df = pd.DataFrame(json.loads(data))
#"""

# # TODO: insert file name
# fire_data = pull_from_gcs('file')
# fire_df = 
# # TODO: insert file name
#earthquake_data = pull_from_gcs('earthquake_data')

#earthquake_json = json.loads(earthquake_data)
#earthquake_df = pd.DataFrame(
#    [quake["properties"] for quake in earthquake_json["features"]]
#)
#earthquake_df["time"] = pd.to_datetime(earthquake_df["time"], unit="ms")
#st.title("Earthquakes")
#st.dataframe(earthquake_df[["time", "mag", "place"]])
# # earthquake_df = 
# # TODO: insert file name
fema_data = pull_from_gcs('data/processed/fema_declarations_ca_clean.csv')
fema_df = pd.read_csv(io.BytesIO(fema_data))

# ---------- SECTION 1: declarations per year ----------
st.header("FEMA declarations per year")
st.write("FM = Fire Management (pays for firefighting only), "
         "DR = Major Disaster, EM = Emergency")

fema_df["year"] = fema_df["declarationDate"].str[:4]
# one row per disaster, not per county
disasters = fema_df.drop_duplicates(subset="disasterNumber")
per_year = pd.crosstab(disasters["year"], disasters["declarationType"])
st.bar_chart(per_year)
total = len(disasters)
fm_count = (disasters["declarationType"] == "FM").sum()
dr_count = (disasters["declarationType"] == "DR").sum()

st.write(f"Since 2016 FEMA made {total} fire and earthquake declarations "
         f"in California. {fm_count} of them ({fm_count / total:.0%}) were "
         f"Fire Management declarations, which only cover firefighting "
         f"costs. Only {dr_count} were Major Disasters, the main type that "
         f"can include aid for individual residents.")


#---total per county--
county_df = fema_df.groupby("designatedArea")[
    ["validRegistrations", "approvedForFemaAssistance",
     "totalApprovedIhpAmount"]].sum().reset_index()

# keep counties with at least 100 applicants
county_df = county_df[county_df["validRegistrations"] >= 100]

county_df["approval_rate"] = (county_df["approvedForFemaAssistance"]
                              / county_df["validRegistrations"] * 100)
county_df["dollars_per_applicant"] = (county_df["totalApprovedIhpAmount"]
                                      / county_df["validRegistrations"])

# approval rating

st.header("% of applicants approved for FEMA aid, by county")
st.bar_chart(county_df.head(15), x="designatedArea", y="approval_rate",
             sort="-approval_rate")
st.write("Shows the approval rating by county")

st.header("Aid by county")
st.dataframe(county_df.sort_values("approval_rate", ascending=False),
             hide_index=True)

# # TODO: insert file name
st.header("Per capita income vs. FEMA approval rate")

income_data = pull_from_gcs("acs/clean/per_capita_income.csv")

income_df = pd.read_csv(io.BytesIO(income_data), dtype={"FIPS": str})
income_df = income_df.rename(columns={"FIPS": "county_fips",
                                      "Est_per_capita_income": "per_capita_income"})
#Since pandas reads 06007 as 6007, we want that 0 since it shows it cali
fema_df["county_fips"] = fema_df["county_fips"].astype(str).str.zfill(5)

fema_by_county = fema_df.groupby(["county_fips", "designatedArea"])[
    ["validRegistrations", "approvedForFemaAssistance"]].sum().reset_index()

fema_by_county = fema_by_county[fema_by_county["validRegistrations"] >= 100]
fema_by_county["approval_rate"] = (fema_by_county["approvedForFemaAssistance"]
                                   / fema_by_county["validRegistrations"] * 100)

income_aid = fema_by_county.merge(
    income_df[["county_fips", "per_capita_income"]], on="county_fips")

st.scatter_chart(income_aid, x="per_capita_income", y="approval_rate")

correlation = income_aid["per_capita_income"].corr(income_aid["approval_rate"])
st.write(f"Each dot is a county with at least 100 FEMA applicants "
         f"({len(income_aid)} counties). Correlation between income and "
         f"approval rate: {correlation:.2f} (-1 = richer counties approved "
         f"less, 0 = no relationship, 1 = richer counties approved more).")

st.dataframe(income_aid.sort_values("per_capita_income"), hide_index=True)


# # TODO: insert file name
# census_race = pull_from_gcs('file')

# # TODO: insert file name
# census_sex_age = pull_from_gcs('file')

st.title("FEMA Testing")

st.dataframe(fema_df)