"""
Step 0 (optional): re-export the sheets we use from a new Excel file.

Why this script exists
-----------------------
The original Excel workbook is large (several MB) because other sheets
contain embedded photos. We don't need those to make the map, and we
don't want to commit a multi-megabyte file with photos to the project.
So this script pulls out just the sheets we actually use and saves each
as a small, plain CSV file that the rest of the pipeline reads from:

  - "Aggregert data" -- the main culvert survey data (steps 1-5)
  - "Prioritering av stikkrenner" -- the biologists' own field
    assessment for a subset of culverts: is this an anadromous-fish
    reach, their own priority ranking, and what kind of fix it needs
    (step 6)
  - "SØ naturlig hunder" -- real, field-observed natural migration
    barriers (as opposed to the gradient-based estimate in step 4)
    (step 6)

You only need to run this again if you get an UPDATED Excel file from
your colleagues (e.g. next year's survey data). Point it at the new
file and it will refresh all three CSVs in data/raw/.

Usage
-----
    python scripts/00_eksporter_fra_excel.py path/to/All_kulvertdata_samla_Agder.xlsx
"""

import sys
from pathlib import Path

import pandas as pd

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"

SHEETS = {
    "Aggregert data": RAW_DIR / "aggregert_data_raw.csv",
    "Prioritering av stikkrenner": RAW_DIR / "prioritering_stikkrenner_raw.csv",
    "SØ naturlig hunder": RAW_DIR / "naturlige_hindre_felt_raw.csv",
}


def main():
    if len(sys.argv) != 2:
        print("Usage: python scripts/00_eksporter_fra_excel.py <path-to-excel-file.xlsx>")
        sys.exit(1)

    excel_path = Path(sys.argv[1])
    if not excel_path.exists():
        print(f"Could not find file: {excel_path}")
        sys.exit(1)

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for sheet_name, output_csv in SHEETS.items():
        print(f"Reading sheet '{sheet_name}' from {excel_path} ...")
        df = pd.read_excel(excel_path, sheet_name=sheet_name)
        df.to_csv(output_csv, index=False)
        print(f"  saved {len(df)} rows x {len(df.columns)} columns to {output_csv}")


if __name__ == "__main__":
    main()
