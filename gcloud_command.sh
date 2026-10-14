#!/usr/bin/env bash
#
# gcloud_command.sh — deploy and schedule this project on GCP.
#
#   ./gcloud_command.sh all        # everything, in order (first-time setup)
#   ./gcloud_command.sh bootstrap  # enable APIs, upload your key to Secret Manager
#   ./gcloud_command.sh api        # redeploy the API only
#   ./gcloud_command.sh web        # redeploy the web app only
#   ./gcloud_command.sh scheduler  # (re)create the Cloud Scheduler job only
#   ./gcloud_command.sh urls       # print the deployed URLs
#
# This deploys straight from source with `gcloud run deploy --source`, the
# same way HW3 did. 
#
# Also, make any necessary updates. - Your data should be regularly collected by the scheduler.

set -euo pipefail

# ─── CONFIG : UPDATE THIS : ADD COMMENTS TO FILL IN. ──────────────────────────────────────────────────────────────────
PROJECT_ID="the-natural-disasters"      # your gcp project ID, e.g. "my-gcp-project-12345"
REGION="us-west1"                       # keep the same region everywhere

API_SERVICE="api-server"                # Cloud Run service name for the API
WEB_SERVICE="webapp"                    # Cloud Run service name for Streamlit

API_DIR="./api"                     # folder holding the API Dockerfile
WEB_DIR="./streamlit"                   # folder holding the Streamlit Dockerfile

API_PORT=8000                           # must match EXPOSE/CMD in fastapi/
WEB_PORT=8501                           # Streamlit default

# The key goes to Secret Manager and is mounted at runtime, and .env is read by gcloud at deploy time.
ENV_FILE=".env"
LOCAL_KEY_FILE="/tmp/gcp-key.json"

# The code reads GCP_SERVICE_ACCOUNT_KEY as a file path and mount it
GCP_KEY_SECRET="group-hw3-gcp-key"
SECRET_MOUNT_PATH="/run/secrets/gcp_key"

SCHEDULER_JOB="collect-data"
SCHEDULE="0 0 1 1 *"
SCHEDULER_TZ="America/Los_Angeles"
COLLECT_PATH="/collect"
MESSAGE_BODY='{}'
# ─────────────────────────────────────────────────────────────────────────────

# ─── validation ──────────────────────────────────────────────────────────────
for _var in PROJECT_ID REGION API_SERVICE WEB_SERVICE API_DIR WEB_DIR \
            API_PORT WEB_PORT ENV_FILE LOCAL_KEY_FILE GCP_KEY_SECRET \
            SECRET_MOUNT_PATH SCHEDULER_JOB SCHEDULE COLLECT_PATH; do
  if [ -z "${!_var}" ]; then
    echo "ERROR: $_var is empty -- fill in the CONFIG block at the top of" \
         "this script before running it." >&2
    exit 1
  fi
done
unset _var

if [ "$PROJECT_ID" = "your-gcp-project-id" ]; then
  echo "ERROR: PROJECT_ID is still the placeholder. Edit the CONFIG block." >&2
  exit 1
fi
if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: ENV_FILE '$ENV_FILE' does not exist." \
       "Copy .env_template to .env and fill it in." >&2
  exit 1
fi
if [ ! -f "$LOCAL_KEY_FILE" ]; then
  echo "ERROR: LOCAL_KEY_FILE '$LOCAL_KEY_FILE' does not exist." >&2
  exit 1
fi
for _dir in "$API_DIR" "$WEB_DIR"; do
  if [ ! -f "$_dir/Dockerfile" ]; then
    echo "ERROR: no Dockerfile in '$_dir'." >&2
    exit 1
  fi
done
unset _dir

log() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }

# ─── one-time project setup ──────────────────────────────────────────────────
bootstrap() {
  gcloud config set project "$PROJECT_ID"
  gcloud config set run/region "$REGION"
  gcloud services enable \
    run.googleapis.com \
    cloudbuild.googleapis.com \
    cloudscheduler.googleapis.com \
    secretmanager.googleapis.com \
    storage.googleapis.com

  log "Storing the service account key in Secret Manager as '${GCP_KEY_SECRET}'"
  if ! gcloud secrets describe "$GCP_KEY_SECRET" >/dev/null 2>&1; then
    gcloud secrets create "$GCP_KEY_SECRET" --replication-policy=automatic
  fi
  gcloud secrets versions add "$GCP_KEY_SECRET" --data-file="$LOCAL_KEY_FILE"

  log "Letting the Cloud Run runtime service account read that secret"
  local project_number
  project_number=$(gcloud projects describe "$PROJECT_ID" \
    --format="value(projectNumber)")
  gcloud secrets add-iam-policy-binding "$GCP_KEY_SECRET" \
    --member="serviceAccount:${project_number}-compute@developer.gserviceaccount.com" \
    --role=roles/secretmanager.secretAccessor
}

# ─── API service ─────────────────────────────────────────────────────────────
deploy_api() {
  log "Deploying ${API_SERVICE} from ${API_DIR} (Cloud Build builds the image)"
  gcloud run deploy "$API_SERVICE" \
    --source "$API_DIR" \
    --region "$REGION" \
    --port="$API_PORT" \
    --allow-unauthenticated \
    --timeout=300 \
    --max-instances=1 \
    --env-vars-file="$ENV_FILE" \
    --set-secrets="$SECRET_MOUNT_PATH=$GCP_KEY_SECRET:latest"

  # .env points GCP_SERVICE_ACCOUNT_KEY at a path on your laptop.
  gcloud run services update "$API_SERVICE" \
    --region "$REGION" \
    --update-env-vars=GCP_SERVICE_ACCOUNT_KEY="$SECRET_MOUNT_PATH"
}

api_url() {
  local url
  url=$(gcloud run services describe "$API_SERVICE" \
    --region "$REGION" --format="value(urls[0])")
  if [ -z "$url" ]; then
    url=$(gcloud run services describe "$API_SERVICE" \
      --region "$REGION" --format="value(status.url)")
  fi
  if [ -z "$url" ]; then
    echo "ERROR: could not resolve the URL for Cloud Run service" \
         "'$API_SERVICE' in $REGION. Deploy it first." >&2
    exit 1
  fi
  echo "$url"
}

# ─── Web app ─────────────────────────────────────────────────────────────────
deploy_web() {
  local url; url="$(api_url)"

  log "Deploying ${WEB_SERVICE} from ${WEB_DIR}, pointing at ${url}"
  gcloud run deploy "$WEB_SERVICE" \
    --source "$WEB_DIR" \
    --region "$REGION" \
    --port="$WEB_PORT" \
    --allow-unauthenticated \
    --max-instances=1 \
    --env-vars-file="$ENV_FILE" \
    --set-secrets="$SECRET_MOUNT_PATH=$GCP_KEY_SECRET:latest"

  # API_SERVICE_URL is only discoverable after the API is deployed.
  gcloud run services update "$WEB_SERVICE" \
    --region "$REGION" \
    --update-env-vars=GCP_SERVICE_ACCOUNT_KEY="$SECRET_MOUNT_PATH",API_URL="$url"
}

# ─── Cloud Scheduler ─────────────────────────────────────────────────────────
deploy_scheduler() {
  local url; url="$(api_url)"

  # create the first time, update on every run after that
  local action=create
  if gcloud scheduler jobs describe "$SCHEDULER_JOB" \
       --location="$REGION" >/dev/null 2>&1; then
    action=update
  fi

  log "Running '${action}' on scheduler job '${SCHEDULER_JOB}' (${SCHEDULE} ${SCHEDULER_TZ})"
  gcloud scheduler jobs "$action" http "$SCHEDULER_JOB" \
    --location="$REGION" \
    --schedule="$SCHEDULE" \
    --time-zone="$SCHEDULER_TZ" \
    --uri="${url}${COLLECT_PATH}" \
    --http-method=POST \
    --headers="Content-Type=application/json" \
    --message-body="$MESSAGE_BODY"

  log "Triggering the job once so you can confirm it works"
  gcloud scheduler jobs run "$SCHEDULER_JOB" --location="$REGION"
  echo "Check the result with:"
  echo "  gcloud run services logs read ${API_SERVICE} --region=${REGION} --limit=50"
}

show_urls() {
  echo "API     : $(api_url)"
  echo "Web app : $(gcloud run services describe "$WEB_SERVICE" \
    --region "$REGION" --format='value(status.url)')"
}

# ─── entry point ─────────────────────────────────────────────────────────────
case "${1:-all}" in
  all)       bootstrap; deploy_api; deploy_web; deploy_scheduler; show_urls ;;
  bootstrap) bootstrap ;;
  api)       deploy_api ;;
  web)       deploy_web ;;
  scheduler) deploy_scheduler ;;
  urls)      show_urls ;;
  *) echo "usage: $0 {all|bootstrap|api|web|scheduler|urls}" >&2; exit 1 ;;
esac

log "Done."
