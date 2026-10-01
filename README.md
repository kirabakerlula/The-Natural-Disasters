# The-Natural-Disasters
DSAI-692 Data Acquisitions Group Projet 

## Team Members

| Name | GitHubID | Role / Focus |
| --- | --- | --- |
| Alex Goldstone | agold21 | fast api .py, requirement.txt,  + github review |
| Alejandro Mancillas | DJ-Taco | README.md and Demographic Data |
| Yu Chia Chang | YUJIACHANG | USGS + CAL FIRE API testing, data exploration, join key planning |
| Kira Baker | kirabakerlula | GitHub/GCP |
| Rishi Burt-Iyer | rishiiyer1 | .py file for fema/usgs |
---


## Problem Statement
- The Natural Disasters wants to investigate how demographic factors, such as income and race, can relate to how federal aid is distributed towards communites in california affected by earthquakes and wildfires. 

---

## Data Sources and Integration Goal
- 

### Sources
| 1 | [FEMA](https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries) | API | Fema event id, type, name, state, dates, location | Dynamic Updates | Free Key |
| 2 | [Cal Fire](https://exact-url) | API | Wildire Data in CA | Dynamic Updates | No Key Needed |
| 3 | [US Census](https://data.census.gov) | API | Demographic Data | Yearly | Free Key |
| 4 | [USGS] (https://earthquake.usgs.gov/earthquakes/search/) | API | Earthquake Data | Dynamic Updates | Free Key, 1000 calls per hour |


### Integration Goal
- Our goal is to be able to integrate by location, namely by county name. By themselves, each data source only tells one part of the story, whether it be demographic, earthquake, wildfire, or FEMA response. All together, these sources will be able to tell the complete story of what happened, who it happened to, and the effects.

---

## Setup Instructions (Locally)

### Prerequisites
- Python 3.11+
- A GCP service account key with access to PROJECT/BUCKET/DATASET
- Any source API keys listed in the table below

### 1. Clone the repository
```bash
git clone https://github.com/ORG/REPO.git
cd REPO
```

### 2. Configure environment variables
Copy the example file and fill in your own values:
CENSUS_API_KEY=
GCS_SERVICE_ACCOUNT_KEY
GCS_BUCKET=
GCP_PROJECT_ID=
FEMA_URL=
USGS_EARTHQUAKE_BASE_URL=
CAL_FIRE_URL= 

```bash
cp .env_template .env
```

| Variable | Description | Example |
| --- | --- | --- |
| `GCP_SERVICE_ACCOUNT_KEY` | Absolute path to your service account JSON | `/Users/you/.ssh/key.json` |
| `GCS_BUCKET` | Name of your designated GCS bucket | `BUCKET_123` |
| `GCP_PROJECT_ID` | Project ID tied to your GCS | `PROJECTID_123` |
| `FEMA_URL` | FEMA API key | `df3kj3002......` |
| `USGS_EARTHQUAKE_BASE_URL` | USGS Earthquake API Key | `39jr24ooire.....` |
| `CAL_FIRE_URL` | Cal Fire API Key | `jowljfe8w90u94.....` |

### 4. How to call your endpoint
To start the API server,
```
fastapi run collect_store_data.py
```

```python
requests.get("http://localhost:8000/source/{source}")
```

---
## Repository Structure
```
.
├──exploration
├── fema_data_pull.ipynb
├──fastapi
├── call_apis.py
├── collect_store_data.py
├── test_upload.ipynb
├──hazard_data
├── calfire_sample.py
├── calfire_wildfires_2016_2026.csv
├── usgs_california_earthquakes_2016_2026.csv
├── usgs_sample.py
├──.gitignore
├──LICENSE
├──README.md
├──.env_template
├──fema_declarations.py
└──requirments.txt
```
