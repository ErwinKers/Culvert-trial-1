"""
Step 5 (optional): add real hydrology data to the map -- how much water
each stream carries on average, plus a rough estimate of its width and
flow speed, and the real lake polygons NVE already maps as proper
areas (not just lines).

Why this is useful
-------------------
A thin blue line on a map doesn't tell you whether something is a
trickle you could step over or a real river. This script attaches:

  - **Average discharge** ("vannføring", in m3/s): a genuine NVE
    number, not a guess -- see "Where the discharge number comes from"
    below.
  - **Estimated width and flow speed**: there is no NVE dataset of
    measured channel width or velocity for every stream in this
    export, so these two are calculated from the discharge using
    standard textbook "hydraulic geometry" formulas (channel
    dimensions scale with a power of discharge -- see Leopold & Maddock
    1953 for the classic reference). They are clearly labelled
    "estimated" everywhere they show up, and should be read as
    "roughly this order of magnitude", not a survey measurement.
  - **Lakes**: NVE's own lake polygons, which are real, measured area
    features (not estimated at all) -- these alone already make a good
    chunk of "the water system" appear as proper area instead of a
    line.

This produces a river-width "ribbon" polygon per stream segment
(rendered on the map as an area instead of a plain line) plus a lake
layer, both in `data/processed/`.

Where the discharge number comes from
----------------------------------------
NVE's REGINE catchment units (`Nedborfelt_RegineEnhet`) carry, per the
official field definitions (see this project's NVE metadata PDFs,
`ObjekttyperEgenskaper_Nedborfelt.pdf`):

  - `enhAreal`  = this unit's OWN (local) catchment area, km2
  - `totAreal`  = the area UPSTREAM of this unit (not including its own), km2
  - `regineQ`   = this unit's OWN mean annual inflow, 1991-2020, million m3/year
  - `totTilsig` = the mean annual inflow from UPSTREAM, 1991-2020, million m3/year

So the TOTAL water draining through a unit is (enhAreal + totAreal) for
area, and (regineQ + totTilsig) for annual volume. Converting the
volume to a mean flow rate:

    Q (m3/s) = (regineQ + totTilsig) * 1,000,000 / (365.25 * 24 * 3600)

Each Elvenett river segment carries a `vassdragNr` REGINE code that
matches one of these units exactly (we checked: 883/883 segments in
the Arendal export matched), so every segment gets that unit's Q.
Since one REGINE unit typically covers many individual river segments,
this assigns the SAME discharge to every segment within a unit -- a
step-function approximation, not a smooth increase heading downstream,
but still real, sourced hydrological data rather than a guess.

Usage
-----
    python scripts/05_hent_elveegenskaper.py \\
        --river data/raw/nve_elvenett/Elv_Elvenett.shp \\
        --regine data/raw/nve_nedborfelt/Nedborfelt_RegineEnhet.shp \\
        --innsjo data/raw/nve_innsjo/Innsjo_Innsjo.shp
"""

import argparse
import json
from pathlib import Path

import geopandas as gpd
from shapely.geometry import mapping

ROOT = Path(__file__).resolve().parent.parent
OUT_RIVER_GEOJSON = ROOT / "data" / "processed" / "elvenett_egenskaper.geojson"
OUT_LAKE_GEOJSON = ROOT / "data" / "processed" / "innsjoer.geojson"

WORK_CRS = "EPSG:32632"
SECONDS_PER_YEAR = 365.25 * 24 * 3600

# Hydraulic-geometry coefficients: width_m = WIDTH_A * Q_m3s**WIDTH_B,
# depth_m = DEPTH_A * Q_m3s**DEPTH_B. These are generic, regional-
# average textbook values (Leopold & Maddock-style exponents), NOT
# calibrated against any measurement in this specific area -- treat
# the resulting width/depth/velocity as rough, order-of-magnitude
# estimates only.
WIDTH_A, WIDTH_B = 2.5, 0.5
DEPTH_A, DEPTH_B = 0.3, 0.4
MIN_WIDTH_M = 0.5  # so a trickle doesn't render as a zero-width line


def clean_text(value):
    """Turn pandas' float('nan') for a missing text field into a real
    None, so it doesn't end up serialized as the literal text 'nan'."""
    if value is None or (isinstance(value, float) and value != value):
        return None
    return value


def load_discharge_by_regine(regine_path):
    regine = gpd.read_file(regine_path)
    q_m3s = (regine["regineQ"].fillna(0) + regine["totTilsig"].fillna(0)) * 1_000_000 / SECONDS_PER_YEAR
    area_km2 = regine["enhAreal"].fillna(0) + regine["totAreal"].fillna(0)
    return dict(zip(regine["vassdragNr"], q_m3s)), dict(zip(regine["vassdragNr"], area_km2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--river", default=str(ROOT / "data" / "raw" / "nve_elvenett" / "Elv_Elvenett.shp")
    )
    parser.add_argument(
        "--regine", default=str(ROOT / "data" / "raw" / "nve_nedborfelt" / "Nedborfelt_RegineEnhet.shp")
    )
    parser.add_argument(
        "--innsjo", default=str(ROOT / "data" / "raw" / "nve_innsjo" / "Innsjo_Innsjo.shp")
    )
    args = parser.parse_args()

    print(f"Reading river network from {args.river} ...")
    rivers = gpd.read_file(args.river).to_crs(WORK_CRS)
    rivers = rivers.explode(index_parts=False).reset_index(drop=True)
    rivers = rivers[rivers.geometry.length > 0].reset_index(drop=True)

    print(f"Reading REGINE catchment units from {args.regine} ...")
    q_by_regine, area_by_regine = load_discharge_by_regine(args.regine)

    matched = rivers["vassdragNr"].isin(q_by_regine).sum()
    print(f"  {matched}/{len(rivers)} river segments matched to a REGINE unit")

    features = []
    for _, row in rivers.iterrows():
        q = q_by_regine.get(row["vassdragNr"])
        area = area_by_regine.get(row["vassdragNr"])
        if q is None or q <= 0:
            continue
        width_m = max(MIN_WIDTH_M, WIDTH_A * q**WIDTH_B)
        depth_m = DEPTH_A * q**DEPTH_B
        velocity_m_s = q / (width_m * depth_m) if width_m > 0 and depth_m > 0 else None

        ribbon = row.geometry.buffer(width_m / 2, cap_style="flat")
        ribbon_wgs84 = gpd.GeoSeries([ribbon], crs=WORK_CRS).to_crs("EPSG:4326").iloc[0]
        features.append(
            {
                "type": "Feature",
                "geometry": mapping(ribbon_wgs84),
                "properties": {
                    "elvenavn": clean_text(row.get("elvenavn")),
                    "vassdragNr": row["vassdragNr"],
                    "vannforing_m3s": round(float(q), 3),
                    "nedborfelt_km2": round(float(area), 2) if area is not None else None,
                    "bredde_est_m": round(float(width_m), 2),
                    "dybde_est_m": round(float(depth_m), 2),
                    "hastighet_est_ms": round(float(velocity_m_s), 2) if velocity_m_s else None,
                },
            }
        )

    print(f"Built {len(features)} width-ribbon polygons")
    OUT_RIVER_GEOJSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_RIVER_GEOJSON, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f, ensure_ascii=False, default=str)
    print(f"Saved {OUT_RIVER_GEOJSON}")

    innsjo_path = Path(args.innsjo)
    if innsjo_path.exists():
        print(f"Reading lakes from {innsjo_path} ...")
        lakes = gpd.read_file(innsjo_path).to_crs("EPSG:4326")
        keep_cols = [c for c in ["navn", "areal_km2", "hoyde_moh"] if c in lakes.columns]
        lakes = lakes[keep_cols + ["geometry"]]
        lakes.to_file(OUT_LAKE_GEOJSON, driver="GeoJSON")
        print(f"Saved {len(lakes)} lakes to {OUT_LAKE_GEOJSON}")
    else:
        print(f"No lake file found at {innsjo_path} -- skipping (optional)")


if __name__ == "__main__":
    main()
