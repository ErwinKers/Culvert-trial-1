"""
Step 5 (optional): add NVE's real lake polygons to the map.

Why this is useful
-------------------
A thin blue line for a river doesn't tell you where a lake sits along
it, and a lake is often much more valuable fish habitat per square
metre than the same stretch of stream. NVE's `Innsjo` (lake) dataset
gives us the real, measured lake outlines -- genuine area features, not
an estimate of any kind.

This script just copies those polygons (reprojected to plain
longitude/latitude) to `data/processed/innsjoer.geojson` for step 3 to
draw. The more interesting use of lake data -- factoring lake area into
each culvert's priority score -- happens in step 4
(`04_koble_til_elvenett.py --innsjo ...`), since that's where the
scoring lives; this script is only about the map layer.

A note on lake depth
---------------------
We looked for a usable lake *depth* figure to combine with surface area
into a volume/capacity estimate, since a shallow pond and a deep lake
of the same surface area don't hold the same amount of habitat. NVE's
standard `Innsjo` export carries a `dybdekart` field for exactly this
("does a depth survey exist for this lake"), but for every one of the
201 lakes in the Arendal export it's empty -- no bathymetry is on file
here. So depth is not currently used anywhere in this project; only
surface area (`areal_km2`, a real measured number) feeds into the
priority score. If you can get real depth data for specific lakes
(e.g. from NVE's separate bathymetry surveys, where they exist), that
would be the right number to add -- a rough area-based depth *estimate*
was deliberately left out here, since it would carry the same kind of
unfounded-precision problem as the discharge/width estimate this
project used to have (and dropped).

Usage
-----
    python scripts/05_legg_til_innsjoer.py --innsjo data/raw/nve_innsjo/Innsjo_Innsjo.shp
"""

import argparse
from pathlib import Path

import geopandas as gpd

ROOT = Path(__file__).resolve().parent.parent
OUT_LAKE_GEOJSON = ROOT / "data" / "processed" / "innsjoer.geojson"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--innsjo", default=str(ROOT / "data" / "raw" / "nve_innsjo" / "Innsjo_Innsjo.shp")
    )
    args = parser.parse_args()

    innsjo_path = Path(args.innsjo)
    if not innsjo_path.exists():
        print(f"Could not find lake shapefile at {innsjo_path}")
        raise SystemExit(1)

    print(f"Reading lakes from {innsjo_path} ...")
    lakes = gpd.read_file(innsjo_path).to_crs("EPSG:4326")
    keep_cols = [c for c in ["navn", "areal_km2", "hoyde_moh"] if c in lakes.columns]
    lakes = lakes[keep_cols + ["geometry"]]

    OUT_LAKE_GEOJSON.parent.mkdir(parents=True, exist_ok=True)
    if OUT_LAKE_GEOJSON.exists():
        OUT_LAKE_GEOJSON.unlink()  # geopandas' GeoJSON driver refuses to overwrite in place
    lakes.to_file(OUT_LAKE_GEOJSON, driver="GeoJSON")
    print(f"Saved {len(lakes)} lakes ({lakes['areal_km2'].sum():.2f} km2 total) to {OUT_LAKE_GEOJSON}")


if __name__ == "__main__":
    main()
