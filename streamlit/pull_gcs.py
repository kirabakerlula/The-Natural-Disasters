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
        return e
    return data


"""
IF: data is a csv_file:
df = pd.read_csv(io.BytesIO(data))

IF: data is json:
df = pd.DataFrame(json.loads(data))
"""

# # TODO: insert file name
# fire_data = pull_from_gcs('file')
# # fire_df = 
# # TODO: insert file name
# earthquake_data = pull_from_gcs('earthquake_data')
#df = pd.DataFrame(json.loads(earthquake_data))
# # earthquake_df = 
# # TODO: insert file name
fema_data = pull_from_gcs('data/processed/fema_declarations_ca_clean.csv')
fema_df = pd.read_csv(io.BytesIO(fema_data))

# # TODO: insert file name
# census_income = pull_from_gcs('file')

# # TODO: insert file name
# census_race = pull_from_gcs('file')

# # TODO: insert file name
# census_sex_age = pull_from_gcs('file')

st.title("FEMA Testing")

st.dataframe(fema_df)