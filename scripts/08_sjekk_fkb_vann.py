"""
Step 8 (optional): cross-check culvert positions against FKB-Vann.

Why this exists
----------------
NVE's Elvenett (used in step 4) is a *network* product -- built so that
streams connect properly at confluences and can be traced up/downstream,
which is exactly what this project needs for the upstream-habitat walk.
But it's a generalised dataset, not surveyed at high precision.

FKB-Vann (Felles KartdataBase -- Vann) is Kartverket's detailed
hydrography layer, captured by aerial photogrammetry at much finer
positional accuracy (FKB-A/B/C class) -- genuinely more precise about
*where* a stream actually is. What it does NOT have is Elvenett's
graph structure (confluence nodes, flow direction) -- so it can't
replace Elvenett for the upstream trace, only check it.

So this script does not change the network or the scoring. It just
checks, for each barrier culvert:

1. How far the ORIGINAL FIELD COORDINATE is from the nearest FKB-Vann
   stream line (compare this to `snap_avstand_m`, the same distance to
   the nearest Elvenett line, already computed in step 4).
2. How far the point step 4 actually snapped to (on Elvenett) is from
   the nearest FKB-Vann line -- i.e. at the spot the pipeline already
   chose, do the two datasets even agree where the stream is?

A big number in (2) means the two datasets disagree at that location --
worth a field look, and a strong candidate for why a culvert might have
been one of the 13 flagged in step 4 as snapping >50 m from Elvenett in
the first place. This script only flags disagreements; it deliberately
does not auto-correct any coordinate or feed anything back into the
upstream trace -- that's a decision for a human to make after looking
at the flagged sites, the same caution this project already applies to
the plain Elvenett snap-distance warning.

A note on schema, and on testing
---------------------------------
FKB-Vann's SOSI product spec defines object types including `ElvBekk`
(stream/river centreline), `Kanal` (canal), and polygon-edge types like
`ElvBekkKant` / `Innsjøkant` that are NOT centrelines and should be
excluded from a "nearest stream line" comparison. Real-world shapefile/
GML exports commonly carry an object-type attribute (often `objtype` or
similar, sometimes truncated by older DBF-based tooling) -- but the
exact column name and casing can vary by export tool and vintage, and
this project does not have a real FKB-Vann export to test against (the
sandbox this was written in has no route to Geonorge/Agderkart). So the
column detection below is deliberately defensive: it looks for a
plausible object-type column and filters to stream/canal-like values if
it finds one, but falls back to "use every line geometry in the file"
with a clear warning if it can't find one, rather than silently
filtering out everything (or crashing). If it guesses wrong on your
actual export, the console output tells you exactly what it saw
(column names, sample object-type values) so the filter can be
corrected.

Usage
-----
    python scripts/08_sjekk_fkb_vann.py --fkb path/to/fkb_vann_arendal.shp --kommune Arendal

The input can be anything geopandas/GDAL can read (shapefile, GML,
GeoPackage, GeoJSON) -- whatever format your export/download tool gives
you.
"""

import argparse
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
IN_CULVERT_CSV = ROOT / "data" / "processed" / "kulvert_punkter_oppstrom.csv"
OUT_CSV = ROOT / "data" / "processed" / "kulvert_fkb_sjekk.csv"

# Reproject everything into this flat, metre-based CRS before measuring
# distances -- same one step 4 uses, so distances are directly comparable.
WORK_CRS = "EPSG:32632"

# If the FKB-Vann file has no CRS recorded (some export tools drop the
# .prj), assume this -- the standard delivery CRS for Norwegian FKB
# exports south of Trondheim, including Agder. Not needed if the file's
# own CRS is set correctly, which is the normal case.
ASSUMED_CRS_IF_MISSING = "EPSG:25832"

# A stream-position disagreement bigger than this (metres), at the point
# step 4 already snapped to on Elvenett, gets flagged for a closer look.
DISAGREEMENT_THRESHOLD_M = 15.0

# Object-type values (case-insensitive substring match) that count as a
# stream/river centreline worth comparing against. Deliberately excludes
# "...Kant" types (polygon edges, e.g. ElvBekkKant, Innsjøkant) since
# those trace a bank/shoreline, not the stream itself.
STREAM_LIKE_KEYWORDS = ["elvbekk", "kanal"]
EXCLUDE_KEYWORDS = ["kant"]


def find_objtype_column(gdf):
    candidates = [c for c in gdf.columns if c.lower() in ("objtype", "objekttype", "featuretype", "object_type")]
    return candidates[0] if candidates else None


def filter_to_stream_lines(fkb):
    """Keep only stream/canal centrelines, as best we can tell from the data."""
    col = find_objtype_column(fkb)
    if col is not None:
        values = fkb[col].astype(str)
        print(f"  found object-type column '{col}', values seen: {sorted(values.unique())}")
        keep = values.str.lower().apply(
            lambda v: any(k in v for k in STREAM_LIKE_KEYWORDS) and not any(k in v for k in EXCLUDE_KEYWORDS)
        )
        filtered = fkb[keep]
        if len(filtered) == 0:
            print(
                "  WARNING: none of the object-type values matched "
                f"{STREAM_LIKE_KEYWORDS} -- keeping every line feature instead. "
                "Check the values printed above and adjust STREAM_LIKE_KEYWORDS "
                "in this script if that's wrong."
            )
        else:
            print(f"  kept {len(filtered)} of {len(fkb)} features as stream/canal centrelines")
            return filtered
    else:
        print(
            f"  WARNING: no object-type column found among {list(fkb.columns)} -- "
            "cannot filter by feature type, using every line feature in the file."
        )

    lines_only = fkb[fkb.geometry.geom_type.isin(["LineString", "MultiLineString"])]
    if len(lines_only) < len(fkb):
        print(f"  dropped {len(fkb) - len(lines_only)} non-line feature(s) (polygons etc.)")
    return lines_only


def nearest_distance_m(points, lines_gdf):
    """For each point, the distance (m) to the nearest line in lines_gdf.

    Simple O(n_points x n_lines) approach -- with ~44 culverts this is
    cheap even against a few thousand FKB-Vann segments, and it avoids
    relying on a specific geopandas/rtree spatial-index API version.
    """
    all_lines = lines_gdf.geometry
    return [all_lines.distance(pt).min() for pt in points]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fkb", required=True, help="Path to an FKB-Vann export (shapefile/GML/GeoPackage/...)")
    parser.add_argument("--kommune", default="Arendal")
    args = parser.parse_args()

    fkb_path = Path(args.fkb)
    if not fkb_path.exists():
        print(f"Could not find FKB-Vann file at {fkb_path}")
        raise SystemExit(1)

    if not IN_CULVERT_CSV.exists():
        print(f"Could not find {IN_CULVERT_CSV} -- run scripts/04_koble_til_elvenett.py first.")
        raise SystemExit(1)

    print(f"Reading FKB-Vann from {fkb_path} ...")
    fkb = gpd.read_file(fkb_path)
    print(f"  {len(fkb)} features read, columns: {list(fkb.columns)}")
    if fkb.crs is None:
        print(f"  FKB-Vann file has no CRS set -- assuming {ASSUMED_CRS_IF_MISSING}")
        fkb = fkb.set_crs(ASSUMED_CRS_IF_MISSING)
    fkb = fkb.to_crs(WORK_CRS)

    streams = filter_to_stream_lines(fkb)
    if len(streams) == 0:
        print("No usable line features found in the FKB-Vann file -- nothing to compare against.")
        raise SystemExit(1)

    print(f"Reading {IN_CULVERT_CSV} ...")
    culverts = pd.read_csv(IN_CULVERT_CSV)
    culverts = culverts[culverts["kommune"] == args.kommune].copy()
    print(f"  {len(culverts)} culverts in {args.kommune}")

    field_points = gpd.GeoSeries(
        gpd.points_from_xy(culverts["lon_ned"], culverts["lat_ned"]), crs="EPSG:4326"
    ).to_crs(WORK_CRS)
    snapped_points = gpd.GeoSeries(
        gpd.points_from_xy(culverts["lon_snappet"], culverts["lat_snappet"]), crs="EPSG:4326"
    ).to_crs(WORK_CRS)

    print("Measuring distances to the nearest FKB-Vann stream line ...")
    culverts["fkb_avstand_felt_m"] = nearest_distance_m(field_points, streams)
    culverts["fkb_avstand_snappet_m"] = nearest_distance_m(snapped_points, streams)
    culverts["fkb_uenighet"] = culverts["fkb_avstand_snappet_m"] > DISAGREEMENT_THRESHOLD_M

    out_cols = [
        "id",
        "stedsnavn",
        "kommune",
        "vassdrag",
        "snap_avstand_m",
        "fkb_avstand_felt_m",
        "fkb_avstand_snappet_m",
        "fkb_uenighet",
    ]
    result = culverts[out_cols].round(
        {"snap_avstand_m": 2, "fkb_avstand_felt_m": 2, "fkb_avstand_snappet_m": 2}
    )

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUT_CSV, index=False)
    print(f"Saved {OUT_CSV}")

    n_flagged = int(result["fkb_uenighet"].sum())
    print(
        f"\n{n_flagged} of {len(result)} culverts have the two datasets disagreeing by "
        f"more than {DISAGREEMENT_THRESHOLD_M:.0f} m at the point Elvenett was snapped to."
    )
    if n_flagged:
        print("These are worth a closer look (sorted by disagreement, biggest first):")
        flagged = result[result["fkb_uenighet"]].sort_values("fkb_avstand_snappet_m", ascending=False)
        for _, row in flagged.iterrows():
            print(
                f"  id {row['id']} ({row['stedsnavn']}): {row['fkb_avstand_snappet_m']:.1f} m "
                f"disagreement (Elvenett snap distance was {row['snap_avstand_m']:.1f} m)"
            )


if __name__ == "__main__":
    main()
