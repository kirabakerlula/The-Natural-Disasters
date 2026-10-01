import os
from dotenv import load_dotenv

from google.oauth2 import service_account
from google.cloud import storage

import requests

import json

# get environment variables
load_dotenv()

# GCS related:
service_account_key = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
project_id = os.getenv("GCP_PROJECT_ID")
bucket_name = os.getenv("GCS_BUCKET")

# website related:
fema_url = os.getenv("OPENFEMA_BASE_URL")
earthquake_url = os.getenv("USGS_EARTHQUAKE_BASE_URL")
fire_url = os.getenv("CAL_FIRE_URL")
# TODO: census
api_key = os.getenv("CENSUS_API_KEY")

# Authenticate / get credentials
credentials = service_account.Credentials.from_service_account_file(
    service_account_key)

def read_upload_data(url, params, file_name):
    # read data from URL
    response = requests.get(url, params=params)
    data = response.json()

    # set up GCP bucket
    client = storage.Client(project=project_id, credentials=credentials)
    bucket = client.bucket(bucket_name)
    file = bucket.blob(file_name)

    # write to bucket
    file.upload_from_string(json.dumps(data))

# default message
def default():
    return {"message": "Please give a source to pull from: (earthquake), rest are not implemented yet"}

# use for getting earthquake data
def call_earthquake():
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

    try: 
        read_upload_data(earthquake_url, params, "earthquake_data")
    except Exception as e:
        return e

    return "earthquake data uploaded to bucket!"


# do the get stuff from Jeff
def call_fire():
    #read_upload_data(fire_url, #TODO: file name)
    return "fire"

def call_census():
    return "census"


