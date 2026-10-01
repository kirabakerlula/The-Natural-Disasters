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
| # | Source & Link | Method | What it contains | Update frequency | Access requirements |
| --- | --- | --- | --- | --- | --- |
| 1 | [NAME](https://exact-url) | API | rows, columns, time range, geography — in your own words | daily / monthly / static | free key, 100 req/day |
| 2 | [NAME](https://exact-url) | File | ... | ... | none |
| 3 | [NAME](https://exact-url) | Scraped | ... | ... | `robots.txt` checked DATE |

Note: If we need a key, say which environment variable holds it and make sure that variable also appears in the .env_template

### Integration Goal
- Follow the direction given in the 1st assignment

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

```bash
cp .env_template .env
```

| Variable | Description | Example |
| --- | --- | --- |
| `GCP_SERVICE_ACCOUNT_KEY` | Absolute path to your service account JSON | `/Users/you/.ssh/key.json` |
| `SOURCE_API_KEY` | Key for SOURCE NAME (free tier) | `abc123...` |
| `API_SERVICE_URL` | Where the web app reaches the API | `http://api-server:8000` |

### 4. How to call your endpoint
To start the API server,
```python
fastapi run mycode.py
```

```python
requests.post("http://localhost:8000/something", json=something)
```
Make sure it writes the data in the bucket.

---
## Repository Structure
```
.
├── your_code.py
├── .env_template
└── README.md
```
