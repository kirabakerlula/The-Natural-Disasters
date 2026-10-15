import json
import re

import os
from dotenv import load_dotenv

from google.oauth2 import service_account
from google.cloud import storage
import streamlit as st
import pandas as pd
import io
import plotly.express as px
import requests

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

# Loading data for earthquake and Fema

earthquake = pull_from_gcs("earthquake_data.csv")
earthquake_data =  pd.read_csv(io.BytesIO(earthquake))

fema_data = pull_from_gcs('data/processed/fema_declarations_ca_clean.csv')
fema_df = pd.read_csv(io.BytesIO(fema_data))

#Section 1, numbers that stand out, showing how many people applies, approved, and amnt approved

st.header("FEMA housing aid at a glance")
col1, col2, col3 = st.columns(3)
col1.metric("People who applied", f"{fema_df['validRegistrations'].sum():,.0f}")
col2.metric("People approved", f"{fema_df['approvedForFemaAssistance'].sum():,.0f}")
col3.metric("Dollars approved", f"${fema_df['totalApprovedIhpAmount'].sum():,.0f}")


#section 2, declarations per year

st.header("FEMA declarations per year")
st.write("FM = Fire Management (pays for firefighting only), "
         "DR = Major Disaster, EM = Emergency")

fema_df["year"] = fema_df["declarationDate"].str[:4]
#one row per disaster, not per county
disasters = fema_df.drop_duplicates(subset="disasterNumber")
per_year = pd.crosstab(disasters["year"], disasters["declarationType"])
st.bar_chart(per_year)

#summary numbers for the sentence below the chart
total = len(disasters)
fm_count = (disasters["declarationType"] == "FM").sum()
dr_count = (disasters["declarationType"] == "DR").sum()

st.write(f"Since 2016 FEMA made {total} fire and earthquake declarations "
         f"in California. {fm_count} of them ({fm_count / total:.0%}) were "
         f"Fire Management declarations, which only cover firefighting "
         f"costs. Only {dr_count} were Major Disasters, the main type that "
         f"can include aid for individual residents.")


# County totals

#add up applicants, approvals and dollars for each county

county_df = fema_df.groupby("designatedArea")[
    ["validRegistrations", "approvedForFemaAssistance",
     "totalApprovedIhpAmount"]].sum().reset_index()

# keep counties with at least 100 applicants
county_df = county_df[county_df["validRegistrations"] >= 100]

county_df["approval_rate"] = (county_df["approvedForFemaAssistance"]
                              / county_df["validRegistrations"] * 100)
county_df["dollars_per_applicant"] = (county_df["totalApprovedIhpAmount"]
                                      / county_df["validRegistrations"])



#Section 3 approval rate per county, with number of disasters

st.header("Approval rate per county, and how many disasters occured")
# count separate disasters per county and add it to county_df
disaster_counts = fema_df.groupby("designatedArea")["disasterNumber"].nunique().reset_index(name="disasters")
county_df = county_df.merge(disaster_counts, on="designatedArea")

top15 = county_df.sort_values("approval_rate", ascending=False).head(10)
fig = px.bar(top15, x="designatedArea", y="approval_rate", text="disasters",
             labels={"designatedArea": "", "approval_rate": "% approved"})

# show number disasters above each bar
fig.update_traces(texttemplate="%{text} disasters", textposition="outside")
st.plotly_chart(fig)


#section 4 applied vs approved

st.header("Applied vs. approved, by county, top 10")
top_counties = county_df.sort_values("validRegistrations", ascending=False).head(10)
top_counties = top_counties.rename(columns={"validRegistrations": "Applied",
                                            "approvedForFemaAssistance": "Approved"})
st.bar_chart(top_counties, x="designatedArea", y=["Applied", "Approved"],
             stack=False, x_label="County", y_label="Number of people")


#section 5 -- wildfires vs fema declaration

#teammate's file wildfires (CAL FIRE) + earthquakes (USGS) per county
hazards_data = pull_from_gcs("earthquake_fire_summary.csv")
hazards_df = pd.read_csv(io.BytesIO(hazards_data), dtype={"county_fips": str})

#FEMA per county declarations, and how many of them offered aid to people
fema_df["county_fips"] = fema_df["county_fips"].astype(str).str.zfill(5)
fema_fires = fema_df[fema_df["incidentType"] == "Fire"]
fema_county = fema_fires.groupby("county_fips").agg(
    fema_declarations=("disasterNumber", "nunique"),
    individual_aid=("ihProgramDeclared", "sum")).reset_index()

#left keeps every county, including ones FEMA never declared
fire_response = hazards_df.merge(fema_county, on="county_fips", how="left")
fire_response[["fema_declarations", "individual_aid"]] = (
    fire_response[["fema_declarations", "individual_aid"]].fillna(0))


#chart only counties with at least one declaration
declared = fire_response[fire_response["fema_declarations"] > 0]

fig = px.scatter(declared, x="wildfire_count", y="fema_declarations",
                 hover_name="county_name",
                 labels={"wildfire_count": "Wildfires (CAL FIRE)",
                         "fema_declarations": "FEMA fire declarations"})
st.plotly_chart(fig)

st.write("Each dot is a California county. Counties further right had more "
         "wildfires; counties higher up got more FEMA fire declarations. "
         "If FEMA responded evenly, the dots would form a rising line. "
         "Instead they're scattered: Riverside had the most wildfires (381) "
         "but none of its declarations included aid for individual residents, "
         "and 17 counties never received a FEMA fire declaration at all.")


#section 6 - per capita income vs approval rate 

st.header("Per capita income vs. FEMA approval rate")


#grabing data from bucket
income_data = pull_from_gcs("acs/clean/2024/per_capita_income.csv")
#reading csv, ensuring fips are str
income_df = pd.read_csv(io.BytesIO(income_data), dtype={"FIPS": str})
#columns made into cleaner names
income_df = income_df.rename(columns={"FIPS": "county_fips",
                                      "Est_per_capita_income": "per_capita_income"})

#pandas reads 06007 as 6007, so put the leading 0 back so that values dont get ruined
fema_df["county_fips"] = fema_df["county_fips"].astype(str).str.zfill(5)

#FEMA totals per county, by county code so it can join with Census data
fema_by_county = fema_df.groupby(["county_fips", "designatedArea"])[
    ["validRegistrations", "approvedForFemaAssistance"]].sum().reset_index()

#making sure to keep only counties with at least 100 applicants
fema_by_county = fema_by_county[fema_by_county["validRegistrations"] >= 100]
fema_by_county["approval_rate"] = (fema_by_county["approvedForFemaAssistance"]
                                   / fema_by_county["validRegistrations"] * 100)


#Joining on fips
income_aid = fema_by_county.merge(
    income_df[["county_fips", "per_capita_income"]], on="county_fips")

fig = px.scatter(income_aid, x="per_capita_income", y="approval_rate",
                 hover_name="designatedArea",
                 labels={"per_capita_income": "Per capita income ($)",
                         "approval_rate": "% approved"})
fig.update_traces(marker=dict(size=12))
st.plotly_chart(fig)


correlation = income_aid["per_capita_income"].corr(income_aid["approval_rate"])
st.write(f"Each dot is one county ({len(income_aid)} counties with 100+ FEMA applicants).")
st.write(f"**Correlation: {correlation:.2f}.** Near 0 means income and approval "
         f"rate aren't related; near -1 or 1 means a strong pattern.")

#st.dataframe(income_aid.sort_values("per_capita_income"), hide_index=True)


#section 7 approval rate vs county demographics

st.header("FEMA approval rate vs. who lives in the county")

#Race / ethnicity % Hispanic or Latino, % people of color
race_data = pull_from_gcs("acs/clean/2024/hispanic_or_latino_origin_by_race.csv")
race_df = pd.read_csv(io.BytesIO(race_data), dtype={"FIPS": str})
race_df["pct_hispanic"] = (race_df["Est_Total_Hispanic_or_Latino"]
                           / race_df["Est_Total"] * 100)
race_df["pct_people_of_color"] = 100 - (
    race_df["Est_Total_Not_Hispanic_or_Latino_White_alone"]
    / race_df["Est_Total"] * 100)

# Poverty: % of people below the poverty line
poverty_data = pull_from_gcs("acs/clean/2024/poverty_by_sex_age.csv")

poverty_df = pd.read_csv(io.BytesIO(poverty_data), dtype={"FIPS": str})

#keep only the 3 columns we need (the file has more than 100
poverty_df = poverty_df[["FIPS", "Est_Total",
    "Est_Total_Income_in_the_past_12_months_below_poverty_level"]].copy()
poverty_df["pct_poverty"] = (
    poverty_df["Est_Total_Income_in_the_past_12_months_below_poverty_level"]
    / poverty_df["Est_Total"] * 100)

#One row per county: FEMA + income + race + poverty
demo_df = (fema_by_county
           .merge(income_df[["county_fips", "per_capita_income"]],
                  on="county_fips")
           .merge(race_df.rename(columns={"FIPS": "county_fips"})
                  [["county_fips", "pct_hispanic", "pct_people_of_color"]],
                  on="county_fips")
           .merge(poverty_df.rename(columns={"FIPS": "county_fips"})
                  [["county_fips", "pct_poverty"]],
                  on="county_fips"))

#dropdown: label shown to the user column name in demo_df
measures = {"% below poverty line": "pct_poverty",
            "% Hispanic or Latino": "pct_hispanic",
            "% people of color": "pct_people_of_color",
            "Per capita income ($)": "per_capita_income"}
choice = st.selectbox("Compare approval rate with:", list(measures))
column = measures[choice]

# Butte(County) - "Butte" for shorter dot labels
demo_df["county"] = demo_df["designatedArea"].str.replace(" (County)", "", regex=False)

fig = px.scatter(demo_df, x=column, y="approval_rate",
                 text="county",
                 hover_name="designatedArea",
                 labels={column: choice, "approval_rate": "% approved"})
fig.update_traces(marker=dict(size=14), textposition="top center",
                  textfont=dict(size=10))
st.plotly_chart(fig)

correlation = demo_df[column].corr(demo_df["approval_rate"])
st.write(f"Correlation: {correlation:.2f} across {len(demo_df)} counties "
         f"(-1 to 1, where 0 means no relationship). These are county "
         f"averages, so they can't tell us how FEMA treated individual "
         f"applicants of a given race or income.")

#SECTION 8 counties FEMA never declared, and who lives there

st.header("California counties that had no Fema declarations")

#wildfire + FEMA data per county, joined with income, race and poverty
fire_demo = (fire_response
             .merge(income_df[["county_fips", "per_capita_income"]], on="county_fips")
             .merge(race_df.rename(columns={"FIPS": "county_fips"})
                    [["county_fips", "pct_people_of_color"]], on="county_fips")
             .merge(poverty_df.rename(columns={"FIPS": "county_fips"})
                    [["county_fips", "pct_poverty"]], on="county_fips"))
fire_demo["FEMA declared?"] = fire_demo["fema_declarations"].map(
    lambda n: "Yes" if n > 0 else "Never")

#nicer column names for the tables
nice_names = {"county_name": "County",
              "wildfire_count": "Wildfires",
              "per_capita_income": "Per capita income ($)",
              "pct_poverty": "% in poverty",
              "pct_people_of_color": "% people of color"}


st.write("Counties with no FEMA fire declarations (not shown above). "
         "Without a declaration, residents can't apply for FEMA aid.")
never = fire_demo[fire_demo["FEMA declared?"] == "Never"]
st.dataframe(never[["county_name", "wildfire_count", "per_capita_income",
                    "pct_poverty", "pct_people_of_color"]]
             .sort_values("wildfire_count", ascending=False).round(1)
             .rename(columns=nice_names),
             hide_index=True)

#compare the typical county in each group
st.write("Typical (median) county in each group:")
st.dataframe(fire_demo.groupby("FEMA declared?")[
    ["wildfire_count", "per_capita_income", "pct_poverty",
     "pct_people_of_color"]].median().round(1)
             .rename(columns=nice_names))