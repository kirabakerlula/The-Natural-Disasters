from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import requests
from storage import *
import io

app = FastAPI()


@app.get("/")
def output_something():
    """
    Give the user input into how they should be calling data 
    to be uploaded to out GCS bucket. The user should add either:
    
    /source/"earthquake"
    
    /source/"fire"
    """
    return default()


@app.post("/source/{source}")
def call_apis(source: str):
    """
    Call on the apis! The user should add either:

    /source/"earthquake"
    
    /source/"fire"
    
    If they do not do such, they will recieve and instructive
    error message.    
    """
    if source == "earthquake":
        return call_earthquake()
    elif source == "fire":
        return call_fire()
    else:
        raise HTTPException(
            status_code=404,
            detail="Input 'earthquake' or 'fire'"
        )

@app.post("/summarize")
def make_summary():
    """
    Call on the API to make a summary using the data existing
    within the bucket. If the data has not been uploaded yet, 
    an error will be thrown.
    """
    earthquake_data = pull_from_gcs('earthquake_data.csv')
    if earthquake_data == None:
        raise HTTPException(status_code=404, 
                            detail="Call on API to post earthquake data first!")


    fire_data = pull_from_gcs('fire_data.csv')
    if fire_data == None:
        raise HTTPException(status_code=404, 
                            detail="Call on API to post fire data first!")

    return upload_summary(earthquake_data, fire_data)