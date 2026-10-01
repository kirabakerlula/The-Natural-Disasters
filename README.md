# The-Natural-Disasters
DSAI-692 Data Acquisitions Group Projet

One or two sentences: what question does this project answer, and for whom?

**Live web app:** `https://webapp-xxxxx-uw.a.run.app` ← paste your Cloud Run URL
**API (private):** `https://api-server-xxxxx-uw.a.run.app`

---

## Team Members

| Name | GitHubID | Role / Focus |
| --- | --- | --- |
| FULL NAME | id | e.g. Streamlit app — map |
| FULL NAME | id | e.g. scraping for SF news data + scheduled collection |
| FULL NAME | id | e.g. API call for SF crime data + data cleaning |
| FULL NAME | id | e.g. Streamlit app — interactive bar graph |
| FULL NAME | id | e.g. API call weather data + scheduled collection |

---

## Problem Statement

Carry forward from Phase 1, revised to match what you actually built.

## Data Sources and Integration Goal

### Sources

| # | Source & Link | Method | What it contains | Update frequency | Env var for the key |
| --- | --- | --- | --- | --- | --- |
| 1 | [NAME](https://exact-url) | API | rows, columns, time range, geography — in your own words | daily | `SOURCE_API_KEY` |
| 2 | [NAME](https://exact-url) | File | ... | monthly | none |
| 3 | [NAME](https://exact-url) | Scraped | ... | daily | none (`robots.txt` checked YYYY-MM-DD) |

Every key listed here must also appear in `.env_template`.

### Integration Goal

What does combining these show that no single source does? Name the join key and the granularity.

---

## Repository Structure

```
Group_HW3/
├── api/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py              # FastAPI app: routes only
│   ├── collectors/          # one module per data source
│   │   ├── __init__.py
│   │   ├── source_a.py      # API source
│   │   ├── source_b.py      # file source
│   │   └── source_c.py      # scraped source
│   ├── transform.py         # cleaning + the join across sources
│   └── storage.py           # read/write GCS
├── streamlit/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── streamlit_app.py     # UI only — no data logic
├── gcloud_command.sh        # build, deploy, schedule
├── .env_template
└── README.md
```
Feel free to change the structure and name your own modules, libraries and packages.
---

## API Endpoints

| Method | Path | Purpose | Example |
| --- | --- | --- | --- | --- |
| `POST` | `/collect` | fetch from all sources, clean, write to GCS | `{"date": "2026-10-01"}` |
| `GET` | `/data` | processed records, filterable | `/data?start=2026-09-01&county=Alameda` |
| `GET` | `/raw` | the raw stored payload | `/raw?source=source_a` |
| `GET` | `/health` | liveness check  returns `{"status": "ok"}` |

Document your real endpoints here - But also make sure how to access FastAPI auto-docs (Update them using docstrings)

---

## Setup — Local

### Prerequisites

- Python 3.11+, Docker Desktop, `gcloud` CLI
- A GCP service account key with read/write on your bucket

### 1. Clone and configure

```bash
git clone https://github.com/ORG/REPO.git
cd REPO/Group_HW3
cp .env_template .env     # then fill in your values
```

| Variable | Description | Example |
| --- | --- | --- |
| `GCP_PROJECT_ID` | Your GCP project | `msds692-team3` |
| `GCP_BUCKET_NAME` | Bucket for raw + processed data | `team3-bay-data` |
| `GCP_SERVICE_ACCOUNT_KEY` | Path to the service account JSON | `/tmp/gcp-key.json` |
| `SOURCE_API_KEY` | Key for SOURCE NAME | `abc123...` |
| `API_SERVICE_URL` | Where the web app reaches the API | `http://api-server:8000` |

`.env` and your `*.json` key are in `.gitignore`. **Never commit them.**

### 2. Run both services

On api folder,
```bash
docker build -t api .
```

On streamlit folder,
```bash
docker build -t streamlit .
```

- API docs: http://localhost:8000/docs
- Web app: http://localhost:8501

### 3. Trigger a collection run

```bash
curl -X POST http://localhost:8000/collect -H "Content-Type: application/json" -d '{}'
```

Then confirm the object landed in your bucket.

---

## Setup — Deploy to GCP

Edit the CONFIG block at the top of `gcloud_command.sh`, then:

```bash
./gcloud_command.sh all
```

Or one piece at a time while iterating:

```bash
./gcloud_command.sh bootstrap   # enable APIs, create Artifact Registry repo
./gcloud_command.sh api         # rebuild + redeploy the API
./gcloud_command.sh web         # rebuild + redeploy the web app
./gcloud_command.sh scheduler   # (re)create the Cloud Scheduler job
./gcloud_command.sh urls        # print both service URLs
```

---
 
