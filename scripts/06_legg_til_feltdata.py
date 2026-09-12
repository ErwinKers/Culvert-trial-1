"""
Step 6 (optional): bring in two more sheets from the original Excel
workbook that this project hadn't used yet -- both contain real,
field-collected data rather than anything modelled or estimated.

1. "Prioritering av stikkrenner" ("prioritisation of culverts") --
   the biologists' own field assessment for a subset of the surveyed
   culverts, including:
     - whether it's actually on an anadromous-fish reach ("Anadrom
       strekning?"),
     - their own priority ranking ("Prioritering"),
     - what kind of fix it would need ("Type tiltak": light cleanup,
       minor improvement, extensive rebuild, or "unclear, needs a site
       visit"),
     - a free-text expert comment ("Fagkommentar").
   This sheet uses a different coordinate system (EPSG:25833 / UTM
   zone 33N) than the main "Aggregert data" sheet (EPSG:25832 / UTM
   zone 32N) -- both are real, it's just how the two sheets happened
   to be exported. We match rows to our existing culverts by
   coordinate: 70 of the Arendal rows land within a few centimetres of
   an existing culvert (a match, not a coincidence), so we only accept
   a match within `MATCH_DISTANCE_M` and leave everything else blank
   rather than guessing.

2. "SØ naturlig hunder" ("suspected natural barriers") -- an actual
   field register of observed or suspected natural migration barriers
   (waterfalls, natural rapids), several of them cross-referenced
   against Norway's official salmon register ("Lakseregistret"). This
   is real, ground-truthed data -- a much better source than the
   gradient-based *estimate* in step 4's --dtm/--hoyde-api options,
   wherever it's available. We keep both on the map, clearly
   distinguished, since the field register only has a handful of
   points for any one kommune and the modelled layer covers gaps where
   nobody has been to check yet.

Usage
-----
    python scripts/06_legg_til_feltdata.py --kommune Arendal
"""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import Transformer

ROOT = Path(__file__).resolve().parent.parent
IN_PRIORITERING_CSV = ROOT / "data" / "raw" / "prioritering_stikkrenner_raw.csv"
IN_NATURLIGE_CSV = ROOT / "data" / "raw" / "naturlige_hindre_felt_raw.csv"
IN_CULVERT_CSV_CANDIDATES = [
    ROOT / "data" / "processed" / "kulvert_punkter_oppstrom.csv",
    ROOT / "data" / "processed" / "kulvert_punkter_med_hoyde.csv",
    ROOT / "data" / "processed" / "kulvert_punkter.csv",
]
OUT_CULVERT_CSV = ROOT / "data" / "processed" / "kulvert_punkter_feltdata.csv"
OUT_NATURAL_FELT_GEOJSON = ROOT / "data" / "processed" / "naturlige_hindre_felt.geojson"

# A match closer than this is almost certainly the same physical
# culvert recorded twice; anything further is treated as no match at
# all, rather than guessing.
MATCH_DISTANCE_M = 15.0

PRIORITERING_CRS = "EPSG:25833"  # this sheet's x/y columns
NATURLIGE_CRS = "EPSG:25832"  # this sheet's POINT_X/POINT_Y columns (matches Aggregert data)


def parse_norwegian_number(value):
    if pd.isna(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace("\xa0", "").replace(" ", "").replace(",", ".").replace("−", "-")
    try:
        return float(text)
    except ValueError:
        return None


def clean_text(value):
    if value is None or (isinstance(value, float) and value != value):
        return None
    text = str(value).strip()
    return text if text else None


def nearest_match_distance_m(lon_a, lat_a, lon_b, lat_b):
    """Rough but fast distance in metres between arrays of points,
    good enough at this latitude for a "is this basically the same
    point" check (not for anything precision-critical)."""
    lat_mid = np.radians((lat_a + lat_b) / 2)
    dx = (lon_a - lon_b) * 111_320 * np.cos(lat_mid)
    dy = (lat_a - lat_b) * 110_540
    return np.sqrt(dx**2 + dy**2)


def add_prioritering_data(culverts):
    print(f"Reading {IN_PRIORITERING_CSV} ...")
    prio = pd.read_csv(IN_PRIORITERING_CSV)
    prio["x_num"] = prio["x"].apply(parse_norwegian_number)
    prio["y_num"] = prio["y"].apply(parse_norwegian_number)
    prio = prio.dropna(subset=["x_num", "y_num"]).copy()

    transformer = Transformer.from_crs(PRIORITERING_CRS, "EPSG:4326", always_xy=True)
    prio["lon"], prio["lat"] = transformer.transform(prio["x_num"].values, prio["y_num"].values)

    new_cols = {
        "anadrom_strekning": [],
        "ekspert_prioritering": [],
        "type_tiltak": [],
        "fagkommentar": [],
        "prioritering_avstand_m": [],
    }
    prio_lon, prio_lat = prio["lon"].values, prio["lat"].values

    for _, row in culverts.iterrows():
        dists = nearest_match_distance_m(row["lon_ned"], row["lat_ned"], prio_lon, prio_lat)
        best = np.argmin(dists)
        if dists[best] <= MATCH_DISTANCE_M:
            match = prio.iloc[best]
            new_cols["anadrom_strekning"].append(clean_text(match.get("Anadrom strekning?")))
            new_cols["ekspert_prioritering"].append(clean_text(match.get("Prioritering")))
            new_cols["type_tiltak"].append(clean_text(match.get("Type tiltak")))
            new_cols["fagkommentar"].append(clean_text(match.get("Fagkommentar")))
            new_cols["prioritering_avstand_m"].append(round(float(dists[best]), 1))
        else:
            for k in ("anadrom_strekning", "ekspert_prioritering", "type_tiltak", "fagkommentar"):
                new_cols[k].append(None)
            new_cols["prioritering_avstand_m"].append(None)

    for k, v in new_cols.items():
        culverts[k] = v

    n_matched = culverts["prioritering_avstand_m"].notna().sum()
    n_anadrom = (culverts["anadrom_strekning"] == "Ja").sum()
    print(f"  matched {n_matched} of {len(culverts)} culverts to a field assessment record")
    print(f"  {n_anadrom} confirmed as an anadromous-fish reach ('Anadrom strekning? = Ja')")
    return culverts


def build_natural_felt_geojson(kommune_bbox):
    print(f"Reading {IN_NATURLIGE_CSV} ...")
    natural = pd.read_csv(IN_NATURLIGE_CSV)
    natural["px"] = natural["POINT_X"].apply(parse_norwegian_number)
    natural["py"] = natural["POINT_Y"].apply(parse_norwegian_number)
    natural = natural.dropna(subset=["px", "py"]).copy()

    transformer = Transformer.from_crs(NATURLIGE_CRS, "EPSG:4326", always_xy=True)
    natural["lon"], natural["lat"] = transformer.transform(natural["px"].values, natural["py"].values)

    lon_min, lat_min, lon_max, lat_max = kommune_bbox
    in_area = natural[
        (natural["lon"] >= lon_min) & (natural["lon"] <= lon_max) & (natural["lat"] >= lat_min) & (natural["lat"] <= lat_max)
    ]
    print(f"  {len(in_area)} of {len(natural)} field-registered natural barriers fall in this area")

    features = []
    for _, row in in_area.iterrows():
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [row["lon"], row["lat"]]},
                "properties": {
                    "bekk": clean_text(row.get("Navn_bekk")),
                    "beskrivelse": clean_text(row.get("Beskrivelse")),
                    "registrert": clean_text(row.get("Registreringsdato")) or clean_text(row.get("CreationDate")),
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kommune", default="Arendal")
    args = parser.parse_args()

    culvert_csv = next((p for p in IN_CULVERT_CSV_CANDIDATES if p.exists()), None)
    if culvert_csv is None:
        print("Run scripts/01_rens_kulvertdata.py first.")
        raise SystemExit(1)
    print(f"Reading {culvert_csv} ...")
    culverts = pd.read_csv(culvert_csv)

    if IN_PRIORITERING_CSV.exists():
        culverts = add_prioritering_data(culverts)
    else:
        print(f"No {IN_PRIORITERING_CSV} found -- run scripts/00_eksporter_fra_excel.py first, skipping")

    OUT_CULVERT_CSV.parent.mkdir(parents=True, exist_ok=True)
    culverts.to_csv(OUT_CULVERT_CSV, index=False)
    print(f"Saved {OUT_CULVERT_CSV}")

    if IN_NATURLIGE_CSV.exists():
        # Use the same kommune's culverts (which we know are all inside
        # it) to get a bounding box, since this sheet has no kommune
        # column of its own to filter on directly.
        kommune_culverts = culverts[culverts["kommune"] == args.kommune]
        if kommune_culverts.empty:
            print(f"No culverts found for kommune='{args.kommune}' -- can't bound the search area, skipping")
        else:
            pad = 0.02  # degrees, a small margin around the culvert extent
            bbox = (
                kommune_culverts["lon_ned"].min() - pad,
                kommune_culverts["lat_ned"].min() - pad,
                kommune_culverts["lon_ned"].max() + pad,
                kommune_culverts["lat_ned"].max() + pad,
            )
            geojson = build_natural_felt_geojson(bbox)
            with open(OUT_NATURAL_FELT_GEOJSON, "w", encoding="utf-8") as f:
                json.dump(geojson, f, ensure_ascii=False)
            print(f"Saved {OUT_NATURAL_FELT_GEOJSON}")
    else:
        print(f"No {IN_NATURLIGE_CSV} found -- run scripts/00_eksporter_fra_excel.py first, skipping")


if __name__ == "__main__":
    main()
