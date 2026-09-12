"""
Step 0 (optional): re-export the "Aggregert data" sheet from a new Excel file.

Why this script exists
-----------------------
The original Excel workbook is large (several MB) because other sheets
contain embedded photos. We don't need those to make the map, and we
don't want to commit a multi-megabyte file with photos to the project.
So this script pulls out just the one sheet we need ("Aggregert data")
and saves it as a small, plain CSV file that the rest of the pipeline
reads from.

You only need to run this again if you get an UPDATED Excel file from
your colleagues (e.g. next year's survey data). Point it at the new
file and it will refresh data/raw/aggregert_data_raw.csv.

Usage
-----
    python scripts/00_eksporter_fra_excel.py path/to/All_kulvertdata_samla_Agder.xlsx
"""

import sys
from pathlib import Path

import pandas as pd

SHEET_NAME = "Aggregert data"
OUTPUT_CSV = Path(__file__).resolve().parent.parent / "data" / "raw" / "aggregert_data_raw.csv"


def main():
    if len(sys.argv) != 2:
        print("Usage: python scripts/00_eksporter_fra_excel.py <path-to-excel-file.xlsx>")
        sys.exit(1)

    excel_path = Path(sys.argv[1])
    if not excel_path.exists():
        print(f"Could not find file: {excel_path}")
        sys.exit(1)

    print(f"Reading sheet '{SHEET_NAME}' from {excel_path} ...")
    df = pd.read_excel(excel_path, sheet_name=SHEET_NAME)

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_CSV, index=False)
    print(f"Saved {len(df)} rows x {len(df.columns)} columns to {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
