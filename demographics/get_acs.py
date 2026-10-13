import io
import os
import time
import logging
 
import requests                 
import pandas as pd
from google.oauth2 import service_account
from google.cloud import storage

from dotenv import load_dotenv

load_dotenv()

# can adjust when new ACS data releases
ACS_YEAR = "2024"
# GCS related:
service_account_key = os.getenv("GCP_SERVICE_ACCOUNT_KEY")
project_id = os.getenv("GCP_PROJECT_ID")
bucket_name = os.getenv("GCS_BUCKET")

# Authenticate / get credentials
credentials = service_account.Credentials.from_service_account_file(
    service_account_key)

gcs_raw_folder = "raw/acs/" + ACS_YEAR

script_folder = os.path.dirname(os.path.abspath(__file__))
local_raw_folder = os.path.join(script_folder, "raw_census_data")

tables = {
    "B01001": "Sex by age",
    "B01002": "Median age by sex",
    "B02001": "Race",
    "B03002": "Hispanic or Latino origin by race",
    "B17001": "Poverty status by sex by age",
    "B19001": "Household income brackets",
    "B19013": "Median household income",
    "B19301": "Per capita income",
}

base_url = ("https://www2.census.gov/programs-surveys/acs/summary_file/" + ACS_YEAR + "/table-based-SF/")
data_url = base_url + "data/5YRData/"
docs_url = base_url + "documentation/"

cali_ids = ["0400000US06", "0500000US06"]
expected_rows = 59

max_tries = 3
wait_seconds = 10

# logging will tell us if our cloud run messes up and why
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")

def download_and_keep_lines(url, words_to_keep):
    """
    This will download a census text file to read line by line. It will keep 
    the very first line like the column name and any line that contains at least
    one of the words in words_to_keep. Doing it line by line works because we only need 
    about 59 lines per table and downloading the ENTIRE US ACS file to GCS would be problematic
    """
    logging.info("Downloading %s", url)
    response = requests.get(url, stream=True, timeout=120)
    response.raise_for_status()
    response.encoding = "utf-8"
    kept_lines = []
    line_number = 0
    for line in response.iter_lines(chunk_size=1024*1024, decode_unicode=True):
        line_number = line_number + 1
        if line_number == 1:
            kept_lines.append(line)
            continue
        for word in words_to_keep:
            if word in line:
                kept_lines.append(line)
                break
    logging.info("Read %d lines, keeping %d", line_number, len(kept_lines))
    text = "\n".join(kept_lines)
    table = pd.read_csv(io.StringIO(text), sep="|", dtype=str)
    return table

def download_with_retries(url, words_to_keep):
    """
    This calls the funciton above but if we fail then it waits a bit then tries again
    up to our specified limit (max_tries). Census server can be unreliable
    so this function is like insurance for our whole operation
    """
    for attempt in range(1, max_tries + 1):
        try:
            return download_and_keep_lines(url, words_to_keep)
        except requests.exceptions.RequestException as error:
            logging.warning("Attempt %d of %d failed: %s", attempt, max_tries, error)
            if attempt < max_tries:
                logging.info("Waiting %d seconds before another attempt", wait_seconds)
                time.sleep(wait_seconds)
    raise RuntimeError("Unable to download " + url + " after " + str(max_tries) + " tries")

def save_and_upload(table, file_name, bucket):
    """
    Saves the table as a normal CSV file in a local raw folder
    and then uploads the same csv file to our GCS bucket inside the designatd folder
    """
    os.makedirs(local_raw_folder, exist_ok=True)
    local_path = os.path.join(local_raw_folder, file_name)
    table.to_csv(local_path, index=False)
    logging.info("Saved local copy: %s", local_path)
    gcs_path = gcs_raw_folder + "/" + file_name
    blob = bucket.blob(gcs_path)
    blob.upload_from_filename(local_path, content_type = "text/csv")
    logging.info("Uploaded to gs://%s/%s", bucket_name, gcs_path)

def get_raw_file(url, words_to_keep, file_name, bucket, expected_rows=None):
    """
    One file at a time, this does download, check, save, and upload
    You get a True if it works and False if it doesn't.
    We are also trying to error catch to figure out where we 
    messed up but also still download the other tables that we want
    """
    try:
        table = download_with_retries(url, words_to_keep)
        if expected_rows is not None and len(table) != expected_rows:
            logging.warning("%s has %d rows however we expected %d. Please check file",
                            file_name, len(table), expected_rows)
        save_and_upload(table, file_name, bucket)
        return True
    except Exception as error:
        logging.error("You have failed to get %s: %s", file_name, error)
        return False

def connect_to_gcs():
    """
    building a bit more of a robust function that'll connect to GCS since I had has issues
    earlier connecting to the bucket and pointint things in the right direction
    """
    if service_account_key:
        logging.info("Logging in with the service account key file")
        credentials = service_account.Credentials.from_service_account_file(service_account_key)
        return storage.Client(project=project_id, credentials=credentials)
    else:
        logging.info("No key file set, using default Google login")
        return storage.Client(project=project_id)

# the star of the show below
def main():
    logging.info("Kicking off ACS raw download (%s 5 year release)", ACS_YEAR)
    if bucket_name is None:
        logging.error("GCS_BUCKET env var is not set")
        raise SystemExit(1)
    client = connect_to_gcs()
    bucket = client.bucket(bucket_name)
    failed_files = []
    for table_id, description in tables.items():
        logging.info("-- %s (%s) --", table_id, description)
        url = data_url + "acsdt5y" + ACS_YEAR + "-" + table_id.lower() + ".dat"
        success = get_raw_file(url, cali_ids, table_id + ".csv", bucket, expected_rows)
        if not success:
            failed_files.append(table_id + ".csv")
    logging.info("--- Geography file ---")
    geo_url = docs_url + "Geos" + ACS_YEAR + "5YR.txt"
    success = get_raw_file(geo_url, cali_ids, "geography_labels.csv", bucket, expected_rows)
    if not success:
        failed_files.append("geography_labels.csv")
    logging.info("--- Table shells file ---")
    shells_url = docs_url + "ACS" + ACS_YEAR + "5YR_Table_Shells.txt"
    shell_words = []
    for table_id in tables:
        shell_words.append(table_id + "_")
    success = get_raw_file(shells_url, shell_words, "table_shells.csv", bucket)
    if not success:
        failed_files.append("table_shells.csv")
    if len(failed_files) > 0:
        logging.error("Finished with issues: These files failed: %s", failed_files)
        raise SystemExit(1)
    else:
        logging.info("All done! All %d raw files are in gs://%s/%s/", len(tables) + 2, bucket_name, gcs_raw_folder)

if __name__ == "__main__":
    main()
