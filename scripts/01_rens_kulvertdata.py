"""
Step 1: clean the raw culvert ("kulvert"/"stikkrenne") data and work out a
migration-barrier category + colour for every point, ready to put on a map.

This script does three things, in order:

1. READ the raw data (data/raw/aggregert_data_raw.csv, exported from the
   "Aggregert data" sheet of the Excel workbook).

2. CLEAN the coordinates. In the spreadsheet, coordinates are written the
   Norwegian way, e.g. "423 866,481" (space as thousands separator, comma
   as decimal point). We turn that text into an actual number, and then
   convert it from the surveyors' coordinate system (UTM, zone 32N /
   EPSG:25832 -- this is what was used for this dataset) into the
   longitude/latitude system that web maps understand (EPSG:4326, the
   same system GPS and Google Maps use).

   Each culvert has TWO points: one measured just downstream of the pipe
   and one just upstream. We convert both, because that pair is also what
   lets us look at the height (elevation) difference in step 2.

3. CLASSIFY each culvert as a migration barrier or not, based on the
   column "Justert konsekvens" ("adjusted consequence" -- the biologists'
   final assessment after fieldwork). We turn the free-text values in
   that column into a small, fixed set of categories, each with its own
   colour, so the map is easy to read at a glance:

       Absolutt             -> red    -> total barrier, fish cannot pass
       Partiell              -> orange -> partial barrier, some fish/some conditions
       Nedstrøms hinder      -> purple -> barrier only in the downstream direction
       Ikke hinder           -> green  -> not a barrier, fish pass freely
       Neppe fiskeførende    -> blue   -> stream probably doesn't hold fish anyway
       Ikke angitt / unknown -> gray   -> not assessed / no data

Output: data/processed/kulvert_punkter.csv and .geojson, which the map
script (03_lag_kart.py) reads.
"""

from pathlib import Path

import pandas as pd
from pyproj import Transformer

# --- File locations -------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
RAW_CSV = ROOT / "data" / "raw" / "aggregert_data_raw.csv"
OUT_CSV = ROOT / "data" / "processed" / "kulvert_punkter.csv"
OUT_GEOJSON = ROOT / "data" / "processed" / "kulvert_punkter.geojson"

# The coordinates in this dataset are in "EUREF89 / UTM sone 32N", the
# official EPSG code for that is 25832. Web maps want plain
# longitude/latitude, EPSG code 4326.
SOURCE_CRS = "EPSG:25832"
TARGET_CRS = "EPSG:4326"

# Colour + short label for each barrier category. "Absolutt" is the most
# serious (red), "Ikke hinder" means fish pass fine (green).
BARRIER_STYLE = {
    "Absolutt": {"color": "#d7191c", "label": "Totalt vandringshinder (absolutt)"},
    "Partiell": {"color": "#fdae61", "label": "Delvis vandringshinder (partiell)"},
    "Nedstrøms hinder": {"color": "#984ea3", "label": "Hinder kun nedstrøms"},
    "Ikke hinder": {"color": "#1a9641", "label": "Ikke et vandringshinder"},
    "Neppe fiskeførende": {"color": "#2c7fb8", "label": "Neppe fiskeførende bekk"},
    "Ikke angitt": {"color": "#999999", "label": "Ikke vurdert / mangler data"},
}


def parse_norwegian_number(value):
    """Turn a Norwegian-formatted number like '423\xa0866,481' into a float.

    Norwegian spreadsheets use a space (often a "non-breaking space",
    the invisible character \\xa0) to group thousands, and a comma
    instead of a period for the decimal point. Python's float() doesn't
    understand that, so we strip the spaces and swap the comma for a dot
    before converting.
    """
    if pd.isna(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def classify_barrier(value):
    """Map the many spelling variants in 'Justert konsekvens' to one of
    our fixed categories (see BARRIER_STYLE above)."""
    if pd.isna(value):
        return "Ikke angitt"
    text = str(value).strip()
    text_low = text.lower()
    if text_low in ("", "-", "nan"):
        return "Ikke angitt"
    if text_low == "absolutt":
        return "Absolutt"
    if text_low == "partiell":
        return "Partiell"
    if text_low == "ikke hinder":
        return "Ikke hinder"
    if text_low == "ikke angitt":
        return "Ikke angitt"
    if text_low == "neppe fiskeførende":
        return "Neppe fiskeførende"
    if "nedstr" in text_low:
        return "Nedstrøms hinder"
    # Anything unexpected still gets shown on the map, just greyed out,
    # instead of silently disappearing.
    return "Ikke angitt"


def main():
    print(f"Reading {RAW_CSV} ...")
    df = pd.read_csv(RAW_CSV)
    print(f"  {len(df)} rows read")

    # --- 1. Parse the coordinate columns -----------------------------
    # 'x'/'y'   = downstream point, 'x.1'/'y.1' = upstream point
    df["x_ned"] = df["x"].apply(parse_norwegian_number)
    df["y_ned"] = df["y"].apply(parse_norwegian_number)
    df["x_opp"] = df["x.1"].apply(parse_norwegian_number)
    df["y_opp"] = df["y.1"].apply(parse_norwegian_number)

    before = len(df)
    df = df.dropna(subset=["x_ned", "y_ned"]).copy()
    print(f"  {before - len(df)} rows dropped (no usable downstream coordinate)")
    print(f"  {len(df)} rows remain with coordinates")

    # --- 2. Convert coordinates to longitude/latitude -----------------
    transformer = Transformer.from_crs(SOURCE_CRS, TARGET_CRS, always_xy=True)

    lon_ned, lat_ned = transformer.transform(df["x_ned"].values, df["y_ned"].values)
    df["lon_ned"], df["lat_ned"] = lon_ned, lat_ned

    # The upstream point is missing for some rows -- that's fine, we
    # just leave lon_opp/lat_opp empty for those.
    has_upstream = df["x_opp"].notna() & df["y_opp"].notna()
    df["lon_opp"] = None
    df["lat_opp"] = None
    lon_opp, lat_opp = transformer.transform(
        df.loc[has_upstream, "x_opp"].values, df.loc[has_upstream, "y_opp"].values
    )
    df.loc[has_upstream, "lon_opp"] = lon_opp
    df.loc[has_upstream, "lat_opp"] = lat_opp

    # --- 3. Classify migration barrier status -------------------------
    df["barrier_category"] = df["Justert konsekvens"].apply(classify_barrier)
    df["barrier_color"] = df["barrier_category"].map(lambda c: BARRIER_STYLE[c]["color"])
    df["barrier_label"] = df["barrier_category"].map(lambda c: BARRIER_STYLE[c]["label"])

    print("\nBarrier categories:")
    print(df["barrier_category"].value_counts())

    # --- 4. Keep only the columns the map actually needs --------------
    keep = {
        "SF 2026 ID": "id",
        "Stedsnavn": "stedsnavn",
        "LOK.KOMMUNE": "kommune",
        "Vassdrag": "vassdrag",
        "Regine": "regine",
        "Justert konsekvens": "vurdering_raw",
        "barrier_category": "barrier_category",
        "barrier_color": "barrier_color",
        "barrier_label": "barrier_label",
        "Hva er problemet?": "problem_beskrivelse",
        "Diameter (cm) (omtrentlig, noen er anslåelser derom det var vanskelig å komme nærme nok kulverten for å måle)": "diameter_cm",
        "Lengde": "lengde_m",
        "Kommentar": "kommentar",
        "kommentar utfyllende": "kommentar_utfyllende",
        "lon_ned": "lon_ned",
        "lat_ned": "lat_ned",
        "lon_opp": "lon_opp",
        "lat_opp": "lat_opp",
    }
    out = df[list(keep.keys())].rename(columns=keep)
    # Row number makes a stable ID for rows where "SF 2026 ID" is empty.
    out["id"] = out["id"].fillna(out.index.to_series().astype(str))

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_CSV, index=False)
    print(f"\nSaved cleaned table to {OUT_CSV}")

    # --- 5. Also save as GeoJSON (handy for QGIS or other GIS tools) --
    features = []
    for _, row in out.iterrows():
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [row["lon_ned"], row["lat_ned"]],
                },
                "properties": row.drop(["lon_ned", "lat_ned"]).to_dict(),
            }
        )
    geojson = {"type": "FeatureCollection", "features": features}
    import json

    with open(OUT_GEOJSON, "w", encoding="utf-8") as f:
        json.dump(geojson, f, ensure_ascii=False)
    print(f"Saved GeoJSON to {OUT_GEOJSON}")


if __name__ == "__main__":
    main()
