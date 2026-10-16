import os
from dotenv import load_dotenv

from google.oauth2 import service_account
from google.cloud import storage

import requests
import json
import pandas as pd

from transform import *

from datetime import date

# get environment variables
load_dotenv()

# GCS related:
service_account_key = os.getenv("GCP_SERVICE_ACCOUNT_KEY")
project_id = os.getenv("GCP_PROJECT_ID")
bucket_name = os.getenv("GCS_BUCKET")

# website related:
fema_url = os.getenv("OPENFEMA_BASE_URL")
earthquake_url = os.getenv("USGS_EARTHQUAKE_BASE_URL")
fire_url = os.getenv("CAL_FIRE_URL")

# Authenticate / get credentials
credentials = service_account.Credentials.from_service_account_file(
    service_account_key)

# helper function to upload
def upload_to_gcs(csv_data, file_name):
    # set up GCP bucket
    client = storage.Client(project=project_id, credentials=credentials)
    bucket = client.bucket(bucket_name)
    file = bucket.blob(file_name)

    # write to bucket
    file.upload_from_string(csv_data)

# helper function to pull data from bucket
def pull_from_gcs(file_name):
    # set up GCP bucket
    client = storage.Client(project=project_id, credentials=credentials)
    bucket = client.bucket(bucket_name)
    file = bucket.blob(file_name)
    # pull data from bucket
    try:
        return file.download_as_bytes()
    except:
        return None

# default message
def default():
    return {"message": "Please give a source to pull from as a post: "
    "source/(earthquake, fire). You can summarize after calling both posts!"}

# use for getting earthquake data
def call_earthquake():

    endtime = date.today().isoformat()

    params = {
        "format": "geojson",
        "starttime": "2016-01-01",
        "endtime": endtime,   
        "minmagnitude": 4.0,

        # Approximate California bounding box
        "minlatitude": 32.5,
        "maxlatitude": 42.0,
        "minlongitude": -124.5,
        "maxlongitude": -114.1,
    }

    try: 
        # read data from URL
        response = requests.get(earthquake_url, params=params)
        data = response.json()

        # transform data
        transformed_data = transform_usgs(data)

        # get in csv format for uploading
        csv_data = transformed_data.to_csv(index=False, encoding="utf-8")

        # upload to GCS bucket
        upload_to_gcs(csv_data, 'earthquake_data.csv')

    except Exception as e:
        return e

    return "earthquake data uploaded to bucket!"


# do the get stuff from Jeff
def call_fire():

    all_data = pd.DataFrame()

    endyear = date.today().year + 1

    # have to call year by year
    for year in range(2016, endyear):
        # set up params
        params = {"year": year}
        try: 
            # read data from URL
            response = requests.get(fire_url, params=params)
        except Exception as e:
            return e
        
        data = response.json()

        # transform data
        transformed_data = transform_calfire(data)

        # append to full dataset
        all_data = pd.concat([all_data, transformed_data], ignore_index=True)

    # get in csv format for uploading
    csv_data = all_data.to_csv(index=False, encoding="utf-8")

    # upload to GCS bucket
    try: 
        upload_to_gcs(csv_data, 'fire_data.csv')
    except Exception as e:
        return e
    
    return "fire data uploaded successfully!"

def upload_summary(earthquake_data, fire_data):
    # get a summary!
    summary = summarize_hazards(earthquake_data, fire_data)

    # convert data to csv for uploading to GCS bucket
    csv_data = summary.to_csv(index=False, encoding="utf-8")
    try:
        # upload to GCS
        upload_to_gcs(csv_data, 'earthquake_fire_summary.csv')
    except Exception as e:
        return e
    return "summary uploaded successfully!"





