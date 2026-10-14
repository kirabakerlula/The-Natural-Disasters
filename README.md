# The-Natural-Disasters
DSAI-692 Data Acquisitions Group Project 

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
- The Natural Disasters wants to investigate how demographic factors, such as income and race, can relate to how federal aid is distributed towards communities in California affected by earthquakes and wildfires. 

---

## Data Sources and Integration Goal

### Sources
| # | Source & Link | Method | What it contains | Update frequency | Access requirements |
| --- | --- | --- | --- | --- | --- |
| 1 | [FEMA](https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries) | API | FEMA event id, type, name, state, dates, location | Dynamic Updates | Free Key |\
| 2 | [Cal Fire](https://exact-url) | API | Wildfire Data in CA | Dynamic Updates | No Key Needed |\
| 3 | [US Census](https://data.census.gov) | API | Demographic Data | Yearly | Free Key |\
| 4 | [USGS] (https://earthquake.usgs.gov/earthquakes/search/) | API | Earthquake Data | Dynamic Updates | Free Key, 1000 calls per hour |\


### Integration Goal
- Our goal is to be able to integrate by location, namely by county. By themselves, each data source only tells one part of the story, whether it be demographic, earthquake, wildfire, or FEMA response. All together, these sources will be able to tell the complete story of what happened, who it happened to, and the effects.

---

## Setup Instructions (Locally)

### Prerequisites
- Python 3.11+
- A GCP service account key with access to PROJECT/BUCKET/DATASET
- Any source API keys listed in the table below

### 1. Clone the repository
```bash
git clone https://github.com/kirabakerlula/The-Natural-Disasters.git
cd The-Natural-Disasters
```

### 2. Create the environment

```bash
# Create a virtual environment
python -m venv .venv
source .venv/bin/activate        # macOS/Linux
# .venv\Scripts\activate         # Windows

# Install dependencies
pip install -r requirements.txt
```

### 3. Configure environment variables
Copy the example file and fill in your own values,
```bash
cp .env_template .env
```
### Environment variables

| Variable  | Description | Example |
| --- | --- | --- |
| `CENSUS_API_KEY` | Free US Census API key ([sign up here](https://api.census.gov/data/key_signup.html)) | `your_census_api_key` |
| `GCS_BUCKET` | Name of the GCS bucket that holds the project datasets | `your-bucket-name` |
| `GCP_SERVICE_ACCOUNT_KEY` | Path to your GCP service-account JSON key file | `/path/to/service-account-key.json` |
| `GCP_PROJECT_ID` | ID of the GCP project that contains your bucket | `your-gcp-project-id` |
| `OPENFEMA_BASE_URL` | OpenFEMA Disaster Declarations endpoint (public, no key needed) | `https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries` |
| `USGS_EARTHQUAKE_BASE_URL` | USGS earthquake catalog query endpoint (public, no key needed) | `https://earthquake.usgs.gov/fdsnws/event/1/query` |
| `CAL_FIRE_URL` | Cal Fire incidents endpoint (public, no key needed) | `https://incidents.fire.ca.gov/umbraco/Api/IncidentApi/GetIncidents` |

### 4. How to call your endpoint
To start the API server,
```
fastapi run api/main.py
```

```python
requests.post(f"http://localhost:8000/source/{source}")
```

---
## Repository Structure

```
.
├── demographics/
│   ├── clean_census_data/
│   ├── raw_census_data/
│   └── census_data_cleaning.py
├── exploration/
│   └── fema_data_pull.ipynb
├── api/
│   ├── call_apis.py
│   ├── collect_store_data.py
│   └── test_upload.ipynb
├── hazard_data/
│   ├── calfire_sample.py
│   └── usgs_sample.py
├── .env_template
├── .gitignore
├── fema_declarations.py
├── LICENSE
├── README.md
└── requirements.txt
```
