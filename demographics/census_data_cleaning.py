import os
import re  
import numpy as np
import pandas as pd

script_folder = os.path.dirname(os.path.abspath(__file__))

raw_folder = os.path.join(script_folder, "raw_census_data")
text_columns = ["GEO_ID", "FIPS", "Name"]

def read_census_file(table_id):
    file_path = os.path.join(raw_folder, table_id + ".csv")
    df = pd.read_csv(file_path, encoding="utf-8-sig", dtype=str)
    print("Read", table_id, "->", df.shape[0], "rows,", df.shape[1], "columns")
    return df

def drop_empty_columns(df):
    df = df.dropna(axis="columns", how="all")
    return df

def remove_description_row(df):
    df = df.drop(index=0).reset_index(drop=True)
    return df

def make_clean_name(description, characters_to_remove=""):
    name = description.replace("Margin of Error", "MOE")
    name = name.replace("Estimate", "Est")
    for character in characters_to_remove:
        name = name.replace(character, "")
    name = re.sub("[^A-Za-z0-9_]+", "_", name)
    name = name.strip("_")
    return name

def rename_columns_from_descriptions(df, characters_to_remove=""):
    new_names = []
    for column in df.columns:
        if column == "GEO_ID":
            new_names.append("GEO_ID")
        elif column == "NAME":
            new_names.append("Name")
        else:
            description = df.loc[0, column]
            new_names.append(make_clean_name(description, characters_to_remove))
    if len(new_names) != len(set(new_names)):
        print("STOP RIGHT THERE: some new column names are duplicates!")
    df.columns = new_names
    df = remove_description_row(df)
    return df

def replace_stars_with_null(df):
    df = df.replace("*****", np.nan)
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

# B01001 -> sex_by_age
sex_by_age = read_census_file("B01001")
sex_by_age = drop_empty_columns(sex_by_age)
sex_by_age = rename_columns_from_descriptions(sex_by_age)
sex_by_age = replace_stars_with_null(sex_by_age)
sex_by_age = convert_to_numbers(sex_by_age)
sex_by_age = add_fips_column(sex_by_age)

# B01002 -> median_sex_by_age
median_sex_by_age = read_census_file("B01002")
median_sex_by_age = drop_empty_columns(median_sex_by_age)
median_sex_by_age = rename_columns_from_descriptions(median_sex_by_age)
median_sex_by_age = convert_to_numbers(median_sex_by_age, allow_decimals=True)
median_sex_by_age = add_fips_column(median_sex_by_age)

# B19301 -> per_capita_income 
per_capita_income = read_census_file("B19301")
per_capita_income = drop_empty_columns(per_capita_income)
per_capita_income = remove_description_row(per_capita_income)
per_capita_income.columns = ["GEO_ID", "Name",
                             "Est_per_capita_income",
                             "MOE_per_capita_income"]
per_capita_income = convert_to_numbers(per_capita_income)
per_capita_income = add_fips_column(per_capita_income)

# B19001 -> pop_household_income
pop_household_income = read_census_file("B19001")
pop_household_income = drop_empty_columns(pop_household_income)
pop_household_income = rename_columns_from_descriptions(pop_household_income,
                                                        characters_to_remove="$,")
pop_household_income = convert_to_numbers(pop_household_income)
pop_household_income = add_fips_column(pop_household_income)

# B03002 -> hispanic_or_latino_origin_by_race
hispanic_or_latino_origin_by_race = read_census_file("B03002")
hispanic_or_latino_origin_by_race = drop_empty_columns(hispanic_or_latino_origin_by_race)
hispanic_or_latino_origin_by_race = rename_columns_from_descriptions(hispanic_or_latino_origin_by_race)
hispanic_or_latino_origin_by_race = replace_stars_with_null(hispanic_or_latino_origin_by_race)
hispanic_or_latino_origin_by_race = convert_to_numbers(hispanic_or_latino_origin_by_race)
hispanic_or_latino_origin_by_race = add_fips_column(hispanic_or_latino_origin_by_race)

# B17001 -> poverty_by_sex_age
poverty_by_sex_age = read_census_file("B17001")
poverty_by_sex_age = drop_empty_columns(poverty_by_sex_age)
poverty_by_sex_age = rename_columns_from_descriptions(poverty_by_sex_age)
poverty_by_sex_age = convert_to_numbers(poverty_by_sex_age)
poverty_by_sex_age = add_fips_column(poverty_by_sex_age)

# B02001 -> race
race = read_census_file("B02001")
race = drop_empty_columns(race)
race = rename_columns_from_descriptions(race)
race = replace_stars_with_null(race)
race = convert_to_numbers(race)
race = add_fips_column(race)

# B19013 -> median_household_income
median_household_income = read_census_file("B19013")
median_household_income = drop_empty_columns(median_household_income)
median_household_income = remove_description_row(median_household_income)
median_household_income.columns = ["GEO_ID", "Name",
                                   "Est_Median_household_income",
                                   "MOE_Median_household_income"]
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

clean_folder = os.path.join(script_folder, "clean_census_data")
 
def save_clean_tables(tables, output_folder):
    os.makedirs(output_folder, exist_ok=True)
    for file_name, table in tables.items():
        file_path = os.path.join(output_folder, file_name + ".csv")
        table.to_csv(file_path, index=False)
        print("Saved", file_name + ".csv", "->",
              table.shape[0], "rows,", table.shape[1], "columns")
 
print()
print("=" * 70)
print("Saving the clean tables!")
print("=" * 70)
print("Folder:", clean_folder)
print()
 
save_clean_tables(clean_tables, clean_folder)
 
print()
print("MISSION SUCCESS!", len(clean_tables), "clean tables were saved.")