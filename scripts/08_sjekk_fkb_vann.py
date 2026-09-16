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
FKB-Vann is delivered as (at least) two different real-world product
variants, and this script handles both:

- A **line ("linje") delivery**: SOSI object types `ElvBekk`
  (stream/river centreline) and `Kanal` (canal), plus polygon-edge
  types like `ElvBekkKant` / `Innsjøkant` that are NOT centrelines and
  are excluded. Compared against as "distance to nearest stream line".
- An **area ("område") delivery**: whole water bodies as polygons --
  `Elv` (river, wide enough to be mapped as a polygon rather than a
  single centreline), `Innsjø` (lake), and `Havflate` (open sea, which
  is excluded here since it isn't fish-passage habitat). Compared
  against as "distance to nearest water polygon" -- 0 if the point
  already falls inside one.

Real-world shapefile/GML exports commonly carry an object-type
attribute (often `objtype` or similar, sometimes truncated by older
DBF-based tooling) -- but the exact column name, casing, and value set
can vary by export tool, vintage, and which of the two variants above
you got. So the column/geometry detection below is deliberately
defensive: it looks for a plausible object-type column and filters to
water-feature values for whichever geometry type (line or polygon) the
file actually contains, but falls back to "use every line/polygon
feature in the file" with a clear warning if it can't find that column,
rather than silently filtering out everything (or crashing). If it
guesses wrong on your actual export, the console output tells you
exactly what it saw (column names, sample object-type values) so the
filter can be corrected.

*(Validated against a real Kartverket/Geonorge export: the `område`
polygon variant for Agder, `fkb_vann_omrade` -- 55,727 features,
objtype values `Elv` (20,945), `Innsjø` (32,176), `Havflate` (1,879),
delivered in EPSG:25832 covering the whole county. The `linje` variant
has not been run against a real export.)*

**Important caveat found from that real run, specific to the `område`
variant:** FKB-Vann only digitizes a river as an area polygon once it's
wide enough -- narrow streams simply have no `Elv`/`Innsjø` polygon at
all in this product (they only exist in the `linje` centreline
delivery). So when comparing against an `område` file, a big
`fkb_avstand_*_m` number does NOT necessarily mean the two datasets
disagree about where a stream is -- it can just as easily mean this
particular stream is too narrow to be represented as a polygon at all,
and the "nearest" feature found is actually some unrelated, more
distant river or lake. Confirmed on the real Arendal run: several
culverts with a near-perfect Elvenett snap (under 10 m) still showed
FKB "disagreements" of 400-1000+ m, because the nearest `Elv` polygon
really was that far away -- there was nothing closer to disagree with.
Treat a flagged disagreement from an `område`-type file as "no
comparable FKB-Vann polygon nearby" unless the culvert is known to sit
on a river wide enough to expect one; it is a much more reliable
disagreement signal for the `linje` (centreline) variant, which
represents streams of every size.

Usage
-----
    python scripts/08_sjekk_fkb_vann.py --fkb path/to/fkb_vann_arendal.shp --kommune Arendal

The input can be anything geopandas/GDAL can read (shapefile, GML,
GeoPackage, GeoJSON) -- whatever format your export/download tool gives
you. Since a real export can cover a much bigger area than one kommune
(the Agder-wide `område` file above is one example), this script reads
only the part of it near the culverts being checked, via a bounding-box
filter at read time -- much faster and lighter on memory than loading
the whole file.
"""

import argparse
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import box

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

# How far beyond the culverts' own bounding box to read from the FKB-Vann
# file (metres) -- generous enough that the nearest water feature to an
# edge culvert isn't missed just because it falls slightly outside the
# tightest possible box.
READ_BBOX_BUFFER_M = 500.0

# Object-type values (case-insensitive substring match) that count as a
# stream/river centreline, for a LINE-geometry ("linje") delivery.
# Deliberately excludes "...Kant" types (polygon edges, e.g. ElvBekkKant,
# Innsjøkant) since those trace a bank/shoreline, not the stream itself.
STREAM_LIKE_KEYWORDS = ["elvbekk", "kanal"]
EXCLUDE_LINE_KEYWORDS = ["kant"]

# Object-type values that count as a real water body, for a POLYGON-
# geometry ("område") delivery. "elv" also matches "elvbekk" if that
# ever appears as a polygon. "havflate" (open sea) is excluded -- it's
# not river/lake fish-passage habitat.
WATER_AREA_KEYWORDS = ["elv", "innsjø", "innsjo", "kanal", "ferskvann"]
EXCLUDE_AREA_KEYWORDS = ["havflate"]

LINE_GEOM_TYPES = ["LineString", "MultiLineString"]
POLYGON_GEOM_TYPES = ["Polygon", "MultiPolygon"]


def find_objtype_column(gdf):
    candidates = [c for c in gdf.columns if c.lower() in ("objtype", "objekttype", "featuretype", "object_type")]
    return candidates[0] if candidates else None


def filter_to_water_features(fkb):
    """Keep only real water-body geometries, as best we can tell from the data.

    Branches on whichever geometry type the file actually has: a stream
    line ("linje") delivery is compared as centrelines, a water-body
    polygon ("område") delivery is compared as areas (a point already
    inside one has distance 0).
    """
    geom_types = set(fkb.geometry.geom_type.unique())
    is_line_file = bool(geom_types & set(LINE_GEOM_TYPES))
    is_polygon_file = bool(geom_types & set(POLYGON_GEOM_TYPES))

    if is_line_file:
        keywords, exclude, shape_kind = STREAM_LIKE_KEYWORDS, EXCLUDE_LINE_KEYWORDS, "stream/canal centreline"
        geom_filter = LINE_GEOM_TYPES
    elif is_polygon_file:
        keywords, exclude, shape_kind = WATER_AREA_KEYWORDS, EXCLUDE_AREA_KEYWORDS, "river/lake/canal polygon"
        geom_filter = POLYGON_GEOM_TYPES
        print(
            "  NOTE: this is a polygon (\"område\") FKB-Vann delivery -- it only "
            "digitizes rivers wide enough to be an area, so a big disagreement "
            "below can mean 'no FKB polygon here at all' rather than a real "
            "positional conflict with Elvenett. See the caveat in this script's "
            "docstring before treating a flagged culvert as a real problem."
        )
    else:
        print(f"  WARNING: unexpected geometry type(s) {geom_types} -- cannot filter by feature type, using every feature as-is.")
        return fkb

    col = find_objtype_column(fkb)
    if col is not None:
        values = fkb[col].astype(str)
        print(f"  found object-type column '{col}', values seen: {sorted(values.unique())}")
        keep = values.str.lower().apply(
            lambda v: any(k in v for k in keywords) and not any(k in v for k in exclude)
        )
        filtered = fkb[keep]
        if len(filtered) == 0:
            print(
                f"  WARNING: none of the object-type values matched {keywords} -- "
                f"keeping every {shape_kind.split('/')[0]}-shaped feature instead. "
                "Check the values printed above and adjust WATER_AREA_KEYWORDS/"
                "STREAM_LIKE_KEYWORDS in this script if that's wrong."
            )
        else:
            print(f"  kept {len(filtered)} of {len(fkb)} features as {shape_kind}s")
            return filtered
    else:
        print(
            f"  WARNING: no object-type column found among {list(fkb.columns)} -- "
            f"cannot filter by feature type, using every {shape_kind.split('/')[0]}-shaped feature in the file."
        )

    shape_only = fkb[fkb.geometry.geom_type.isin(geom_filter)]
    if len(shape_only) < len(fkb):
        print(f"  dropped {len(fkb) - len(shape_only)} feature(s) of a different geometry type")
    return shape_only


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

    # A real FKB-Vann export can cover a much bigger area than one kommune
    # (e.g. a whole-county "område" delivery) -- read only a buffered box
    # around this run's culverts, in the FKB file's own CRS, instead of
    # loading the whole file.
    all_points_4326 = gpd.GeoSeries(
        list(gpd.points_from_xy(culverts["lon_ned"], culverts["lat_ned"]))
        + list(gpd.points_from_xy(culverts["lon_snappet"], culverts["lat_snappet"])),
        crs="EPSG:4326",
    ).to_crs(WORK_CRS)
    minx, miny, maxx, maxy = all_points_4326.total_bounds
    bbox_work = box(minx - READ_BBOX_BUFFER_M, miny - READ_BBOX_BUFFER_M, maxx + READ_BBOX_BUFFER_M, maxy + READ_BBOX_BUFFER_M)

    print(f"Reading FKB-Vann from {fkb_path} (bounding box around {args.kommune}'s culverts, +{READ_BBOX_BUFFER_M:.0f} m) ...")
    fkb_file_crs = gpd.read_file(fkb_path, rows=0).crs
    if fkb_file_crs is None:
        print(f"  FKB-Vann file has no CRS set -- assuming {ASSUMED_CRS_IF_MISSING}")
        fkb_file_crs = ASSUMED_CRS_IF_MISSING
    bbox_native = gpd.GeoSeries([bbox_work], crs=WORK_CRS).to_crs(fkb_file_crs).total_bounds
    fkb = gpd.read_file(fkb_path, bbox=tuple(bbox_native))
    print(f"  {len(fkb)} features read within the bounding box, columns: {list(fkb.columns)}")
    if fkb.crs is None:
        fkb = fkb.set_crs(ASSUMED_CRS_IF_MISSING)
    fkb = fkb.to_crs(WORK_CRS)

    if len(fkb) == 0:
        print("No FKB-Vann features found near these culverts -- nothing to compare against.")
        raise SystemExit(1)

    streams = filter_to_water_features(fkb)
    if len(streams) == 0:
        print("No usable water-body features found in the FKB-Vann file -- nothing to compare against.")
        raise SystemExit(1)

    print("Measuring distances to the nearest FKB-Vann water feature ...")
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
