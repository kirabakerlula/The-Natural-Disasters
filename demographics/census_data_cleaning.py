import io
import os
import re
import numpy as np
import pandas as pd
from google.oauth2 import service_account
from google.cloud import storage
 
from dotenv import load_dotenv

load_dotenv()

ACS_YEAR = "2024" #has to match the year from get_acs.py

service_account_key = os.getenv("GCP_SERVICE_ACCOUNT_KEY")
project_id = os.getenv("GCP_PROJECT_ID")
bucket_name = os.getenv("GCS_BUCKET")

gcs_raw_folder = "acs/raw/" + ACS_YEAR
gcs_clean_folder = "acs/clean/" + ACS_YEAR

script_folder = os.path.dirname(os.path.abspath(__file__))
clean_folder = os.path.join(script_folder, "clean_census_data")

text_columns = ["GEO_ID", "FIPS", "Name"]

missing_value_codes = ["-222222222", "-333333333", "-555555555",
                       "-666666666", "-888888888", "-999999999"]

def connect_to_gcs():
    """
    Same function from get_acs.py, this properly handles an error if one occurs
    """
    if service_account_key:
        print("Logging in with the service account key file")
        credentials = service_account.Credentials.from_service_account_file(service_account_key)
        return storage.Client(project=project_id, credentials=credentials)
    else:
        print("No key file set, using default Google login")
        return storage.Client(project=project_id)

def read_from_gcs(file_name, bucket):
    """
    This grabs the csv that get_acs.py uploaded to bucket. We also handle
    We keep the encoding the same because some of the census files start 
    with a "BOM" that would mess up our columns
    """
    gcs_path = gcs_raw_folder + "/" + file_name
    blob = bucket.blob(gcs_path)
    file_bytes = blob.download_as_bytes()
    df = pd.read_csv(io.BytesIO(file_bytes), encoding="utf-8-sig", dtype=str)
    print("Read", gcs_path, "->", df.shape[0], "rows,", df.shape[1], "columns")
    return df

def drop_empty_columns(df):
    df = df.dropna(axis="columns", how="all")
    return df

def make_clean_name(description, characters_to_remove=""):
    name = description.replace("Margin of Error", "MOE")
    name = name.replace("Estimate", "Est")
    for character in characters_to_remove:
        name = name.replace(character, "")
    name = re.sub("[^A-Za-z0-9_]+", "_", name)
    name = name.strip("_")
    return name

def rename_columns_from_shells(df, shells, table_id, characters_to_remove=""):
    this_table = shells[shells["Unique ID"].str.startswith(table_id + "_", na=False)]
    new_names = {}
    labels_so_far = []
    for index, row in this_table.iterrows():
        indent = int(row["Indent"])
        labels_so_far = labels_so_far[:indent]
        labels_so_far.append(row["Label"])
        full_label = " ".join(labels_so_far)
 
        line_number = row["Unique ID"].split("_")[1]
        estimate_code = table_id + "_E" + line_number
        moe_code = table_id + "_M" + line_number
 
        new_names[estimate_code] = make_clean_name("Estimate " + full_label, characters_to_remove)
        new_names[moe_code] = make_clean_name("Margin of Error " + full_label, characters_to_remove)
 
    if len(new_names.values()) != len(set(new_names.values())):
        print("HALT YOURSELF: you got duplicates in your column names!!!")

    df = df.rename(columns=new_names)
 
    for column in df.columns:
        if column.startswith(table_id):
            print("Heads up! no description found for", column)
    return df

def add_name_column(df, geography):
    name_lookup = dict(zip(geography["GEO_ID"], geography["NAME"]))
    names = df["GEO_ID"].map(name_lookup)
    if names.isna().sum() > 0:
        print("Heads up:", names.isna().sum(), "rows didn't get a name")
    df.insert(1, "Name", names)
    return df

def replace_codes_with_null(df):
    df = df.replace(missing_value_codes, np.nan)
    return df

def convert_to_numbers(df, allow_decimals=False):
    for column in df.columns:
        if column in text_columns:
            continue
        df[column] = pd.to_numeric(df[column])
        if allow_decimals:
            df[column] = df[column].astype("float")
        else:
            df[column] = df[column].astype("Int64")
    return df

def add_fips_column(df):
    fips_codes = df["GEO_ID"].str.split("US").str[1].astype(str)
    df.insert(1, "FIPS", fips_codes)
    return df

if bucket_name is None:
    print("GCS_BUCKET is not set, check your .env file")
    raise SystemExit(1)

client = connect_to_gcs()
bucket = client.bucket(bucket_name)

geography = read_from_gcs("geography_labels.csv", bucket)
shells = read_from_gcs("table_shells.csv", bucket)

# B01001 -> sex_by_age
sex_by_age = read_from_gcs("B01001.csv", bucket)
sex_by_age = drop_empty_columns(sex_by_age)
sex_by_age = rename_columns_from_shells(sex_by_age, shells, "B01001")
sex_by_age = add_name_column(sex_by_age, geography)
sex_by_age = replace_codes_with_null(sex_by_age)
sex_by_age = convert_to_numbers(sex_by_age)
sex_by_age = add_fips_column(sex_by_age)

# B01002 -> median_sex_by_age
median_sex_by_age = read_from_gcs("B01002.csv", bucket)
median_sex_by_age = drop_empty_columns(median_sex_by_age)
median_sex_by_age = median_sex_by_age.rename(columns={
    "B01002_E001": "Est_Median_age_Total",
    "B01002_M001": "MOE_Median_age_Total",
    "B01002_E002": "Est_Median_age_Male",
    "B01002_M002": "MOE_Median_age_Male",
    "B01002_E003": "Est_Median_age_Female",
    "B01002_M003": "MOE_Median_age_Female",
})
median_sex_by_age = add_name_column(median_sex_by_age, geography)
median_sex_by_age = replace_codes_with_null(median_sex_by_age)
median_sex_by_age = convert_to_numbers(median_sex_by_age, allow_decimals=True)
median_sex_by_age = add_fips_column(median_sex_by_age)

# B19301 -> per_capita_income 
per_capita_income = read_from_gcs("B19301.csv", bucket)
per_capita_income = drop_empty_columns(per_capita_income)
per_capita_income = per_capita_income.rename(columns={
    "B19301_E001": "Est_per_capita_income",
    "B19301_M001": "MOE_per_capita_income",
})
per_capita_income = add_name_column(per_capita_income, geography)
per_capita_income = replace_codes_with_null(per_capita_income)
per_capita_income = convert_to_numbers(per_capita_income)
per_capita_income = add_fips_column(per_capita_income)

# B19001 -> pop_household_income
pop_household_income = read_from_gcs("B19001.csv", bucket)
pop_household_income = drop_empty_columns(pop_household_income)
pop_household_income = rename_columns_from_shells(pop_household_income, shells, "B19001",
                                                  characters_to_remove="$,")
pop_household_income = add_name_column(pop_household_income, geography)
pop_household_income = replace_codes_with_null(pop_household_income)
pop_household_income = convert_to_numbers(pop_household_income)
pop_household_income = add_fips_column(pop_household_income)

# B03002 -> hispanic_or_latino_origin_by_race
hispanic_or_latino_origin_by_race = read_from_gcs("B03002.csv", bucket)
hispanic_or_latino_origin_by_race = drop_empty_columns(hispanic_or_latino_origin_by_race)
hispanic_or_latino_origin_by_race = rename_columns_from_shells(hispanic_or_latino_origin_by_race, shells, "B03002")
hispanic_or_latino_origin_by_race = add_name_column(hispanic_or_latino_origin_by_race, geography)
hispanic_or_latino_origin_by_race = replace_codes_with_null(hispanic_or_latino_origin_by_race)
hispanic_or_latino_origin_by_race = convert_to_numbers(hispanic_or_latino_origin_by_race)
hispanic_or_latino_origin_by_race = add_fips_column(hispanic_or_latino_origin_by_race)

# B17001 -> poverty_by_sex_age
poverty_by_sex_age = read_from_gcs("B17001.csv", bucket)
poverty_by_sex_age = drop_empty_columns(poverty_by_sex_age)
poverty_by_sex_age = rename_columns_from_shells(poverty_by_sex_age, shells, "B17001")
poverty_by_sex_age = add_name_column(poverty_by_sex_age, geography)
poverty_by_sex_age = replace_codes_with_null(poverty_by_sex_age)
poverty_by_sex_age = convert_to_numbers(poverty_by_sex_age)
poverty_by_sex_age = add_fips_column(poverty_by_sex_age)

# B02001 -> race
race = read_from_gcs("B02001.csv", bucket)
race = drop_empty_columns(race)
race = rename_columns_from_shells(race, shells, "B02001")
race = add_name_column(race, geography)
race = replace_codes_with_null(race)
race = convert_to_numbers(race)
race = add_fips_column(race)

# B19013 -> median_household_income
median_household_income = read_from_gcs("B19013.csv", bucket)
median_household_income = drop_empty_columns(median_household_income)
median_household_income = median_household_income.rename(columns={
    "B19013_E001": "Est_Median_household_income",
    "B19013_M001": "MOE_Median_household_income",
})
median_household_income = add_name_column(median_household_income, geography)
median_household_income = replace_codes_with_null(median_household_income)
median_household_income = convert_to_numbers(median_household_income)
median_household_income = add_fips_column(median_household_income)

clean_tables = {
    "sex_by_age": sex_by_age,
    "median_sex_by_age": median_sex_by_age,
    "per_capita_income": per_capita_income,
    "pop_household_income": pop_household_income,
    "hispanic_or_latino_origin_by_race": hispanic_or_latino_origin_by_race,
    "poverty_by_sex_age": poverty_by_sex_age,
    "race": race,
    "median_household_income": median_household_income,
}

print()
print("=" * 40)
print("Summary of Clean Tables")
print("=" * 40)

for file_name, table in clean_tables.items():
    print()
    print(file_name)
    print("   rows:", table.shape[0], "| columns:", table.shape[1])
    print("   first column names:", list(table.columns[:5]))
    print("   null values in whole table:", table.isna().sum().sum())
    print("   column types:", table.dtypes.astype(str).value_counts().to_dict())

 
def save_and_upload_clean_tables(tables, output_folder, bucket):
    os.makedirs(output_folder, exist_ok=True)
    uploaded_count = 0
    for file_name, table in tables.items():
        local_path = os.path.join(output_folder, file_name + ".csv")
        table.to_csv(local_path, index=False)
        bucket_path = gcs_clean_folder + "/" + file_name + ".csv"
        file = bucket.blob(bucket_path)
        file.upload_from_filename(local_path, content_type="text/csv")
        print("Saved and uploaded", file_name + ".csv", "->",
              table.shape[0], "rows,", table.shape[1], "columns ->",
              "gs://" + bucket_name + "/" + bucket_path)
        uploaded_count = uploaded_count + 1
    return uploaded_count
 
print()
print("=" * 70)
print("Saving + uploading the clean tables!")
print("=" * 70)
print("Local folder:", clean_folder)
print("Bucket folder: gs://" + bucket_name + "/" + gcs_clean_folder)
print()
 
uploaded_count = save_and_upload_clean_tables(clean_tables, clean_folder, bucket)
 
print()
print("MISSION SUCCESS!", len(clean_tables), "clean tables were saved.")