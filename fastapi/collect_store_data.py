from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import requests
from call_apis import *


app = FastAPI()

# create input and output models ?

@app.get("/")
def output_something():
    return default()


@app.get("/source/{source}")
def call_apis(source: str):
    if source == "earthquake":
        return call_earthquake()    
    # elif source == "fire":
    #     return call_fire() 
    # elif source == "census":
    #     return call_census()
    else:
        raise HTTPException(
            status_code = 404,
            detail = "Input 'earthquake'"
        )
    
