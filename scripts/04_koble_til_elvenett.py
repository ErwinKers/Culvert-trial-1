"""
Step 4: snap each culvert onto the real river network, and trace how
much of the river/stream network lies UPSTREAM of it.

Why we need this
-----------------
The culvert coordinates in the spreadsheet aren't perfectly precise
(they were taken in the field, often with a handheld GPS). If we just
trust the raw coordinate, a culvert might appear to sit a few metres off
to the side of the actual stream. So instead we:

  1. Load NVE's "Elvenett" (river network) data -- the same official
     river/stream map data NVE itself uses. Unlike the background map
     tiles from step 3, this is real *line geometry* (actual coordinates
     for every stream/river), which lets us do real spatial analysis,
     not just show a nice-looking picture.
  2. "Snap" each culvert to the closest point on that river network --
     i.e. we assume the culvert is really on the nearest stream, and
     move it there for analysis (and for display) instead of using the
     raw, slightly-off coordinate.
  3. Walk UPSTREAM through the river network graph from that snapped
     point, collecting every stream segment that eventually flows
     into it. That is the stretch of river that would become
     reachable for salmon/sea trout again if this culvert were fixed.
  4. Add up the length of all those segments (in km) as a simple,
     concrete number for "how much habitat opens up".

Only culverts assessed as "Absolutt" (total barrier) or "Partiell"
(partial barrier) are processed -- the rest aren't barriers, so there's
no upstream stretch to "unlock".

Where the river data comes from
--------------------------------
NVE's "Elvenett" is a proper *topological network*: every confluence
(where a stream joins a bigger one) is a break point between two line
features, and lines are digitized in the direction of flow (the first
point of a line is upstream, the last point is downstream). That's
exactly the structure we need to walk the network programmatically.

This script expects the Elvenett shapefile locally, e.g. downloaded
from NVE's map data service (nedlasting.nve.no) or from wherever your
organisation already has it (see the note at the end about where this
project got its copy). Point --river at the .shp file:

    python scripts/04_koble_til_elvenett.py --river data/raw/nve_elvenett/Elv_Elvenett.shp

IMPORTANT -- please sanity-check the flow direction once
----------------------------------------------------------
This script assumes NVE's Elvenett lines are digitized from upstream to
downstream (their documented convention). We could not verify this
against the live data ourselves. Before trusting the results, do a
quick manual check: pick a river you know well (e.g. one that clearly
flows from inland mountains down to the coast), open the cleaned output
in QGIS or similar, and confirm that for a line segment on it, the
first coordinate is the more-inland/upstream end. If it turns out to be
reversed, flip the REVERSE_FLOW_DIRECTION flag below and re-run.
"""

import argparse
from pathlib import Path

import geopandas as gpd
import networkx as nx
import pandas as pd
from shapely.geometry import Point, mapping
from shapely.ops import substring

ROOT = Path(__file__).resolve().parent.parent
IN_CSV_CANDIDATES = [
    ROOT / "data" / "processed" / "kulvert_punkter_med_hoyde.csv",
    ROOT / "data" / "processed" / "kulvert_punkter.csv",
]
OUT_CSV = ROOT / "data" / "processed" / "kulvert_punkter_oppstrom.csv"
OUT_GEOJSON = ROOT / "data" / "processed" / "oppstroms_elvenett.geojson"

# A projected, metre-based coordinate system to do the distance/length
# math in (NVE's own data is delivered in this system, or the very
# close ETRS89 equivalent EPSG:25832 -- close enough here that mixing
# them causes no meaningful error at this scale).
WORK_CRS = "EPSG:32632"

# Two points closer than this (in the graph-node sense) are treated as
# the same confluence point, to absorb tiny floating-point differences
# in how the shared endpoint was stored in each line.
NODE_SNAP_TOLERANCE_M = 1.0

# A culvert whose nearest river point is farther away than this is
# probably not actually matched to the right stream (e.g. a data
# error, or the river layer doesn't cover that spot) -- we still snap
# it (nothing better to do), but flag it clearly so you can review it.
SUSPICIOUS_SNAP_DISTANCE_M = 100.0

BARRIER_COLORS = {"Absolutt": "#d7191c", "Partiell": "#fdae61"}

REVERSE_FLOW_DIRECTION = False  # see the note above


def node_key(coord):
    tol = NODE_SNAP_TOLERANCE_M
    return (round(coord[0] / tol) * tol, round(coord[1] / tol) * tol)


def build_graph(rivers):
    """One directed edge per river line, pointing downstream."""
    G = nx.DiGraph()
    edge_geom = {}
    for idx, geom in enumerate(rivers.geometry):
        if geom is None or geom.length == 0:
            continue
        coords = list(geom.coords)
        if REVERSE_FLOW_DIRECTION:
            coords = coords[::-1]
        start, end = node_key(coords[0]), node_key(coords[-1])
        G.add_edge(start, end, idx=idx, length=geom.length)
        edge_geom[idx] = geom if not REVERSE_FLOW_DIRECTION else geom.reverse()
    return G, edge_geom


def trace_upstream(G, edge_geom, start_node):
    """All edges that flow into start_node, directly or through any
    number of tributaries -- a plain graph walk, so branching river
    networks are handled automatically without double-counting."""
    visited_nodes = {start_node}
    stack = [start_node]
    upstream_idxs = []
    while stack:
        node = stack.pop()
        for pred in G.predecessors(node):
            edge = G.get_edge_data(pred, node)
            upstream_idxs.append(edge["idx"])
            if pred not in visited_nodes:
                visited_nodes.add(pred)
                stack.append(pred)
    return upstream_idxs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--river",
        default=str(ROOT / "data" / "raw" / "nve_elvenett" / "Elv_Elvenett.shp"),
        help="Path to the NVE Elvenett .shp file",
    )
    args = parser.parse_args()

    river_path = Path(args.river)
    if not river_path.exists():
        print(f"Could not find river shapefile at {river_path}")
        print("Download the 'Elv' folder (Elv_Elvenett.shp/.shx/.dbf/.prj) from")
        print("your NVE map data export and place it there, or pass --river.")
        raise SystemExit(1)

    culvert_csv = next((p for p in IN_CSV_CANDIDATES if p.exists()), None)
    if culvert_csv is None:
        print("Run scripts/01_rens_kulvertdata.py first.")
        raise SystemExit(1)

    print(f"Reading river network from {river_path} ...")
    rivers = gpd.read_file(river_path)
    if rivers.crs is None:
        print("River file has no CRS set -- assuming EPSG:32632 (NVE's usual export CRS)")
        rivers = rivers.set_crs(WORK_CRS)
    else:
        rivers = rivers.to_crs(WORK_CRS)
    # A "MultiLineString" can hide several disconnected parts in one
    # row; break those apart so each row is a single, simple line.
    rivers = rivers.explode(index_parts=False).reset_index(drop=True)
    rivers = rivers[rivers.geometry.length > 0].reset_index(drop=True)
    print(f"  {len(rivers)} river line segments")

    print(f"Reading {culvert_csv} ...")
    culverts = pd.read_csv(culvert_csv)
    culverts = culverts[culverts["barrier_category"].isin(BARRIER_COLORS.keys())].copy()
    print(f"  {len(culverts)} culverts are Absolutt/Partiell and will be processed")

    culvert_points = gpd.GeoDataFrame(
        culverts,
        geometry=gpd.points_from_xy(culverts["lon_ned"], culverts["lat_ned"]),
        crs="EPSG:4326",
    ).to_crs(WORK_CRS)

    print("Building the river network graph ...")
    G, edge_geom = build_graph(rivers)

    print("Snapping each culvert to the nearest river segment ...")
    nearest = gpd.sjoin_nearest(
        culvert_points, rivers[["geometry"]], distance_col="snap_avstand_m", how="left"
    )
    # sjoin_nearest can return >1 match per point on exact ties; keep
    # the first (closest) match for each culvert.
    nearest = nearest[~nearest.index.duplicated(keep="first")]

    features = []
    snap_lon, snap_lat, upstream_km, snap_dist_out = [], [], [], []

    for i, row in culvert_points.iterrows():
        river_idx = int(nearest.loc[i, "index_right"])
        dist = float(nearest.loc[i, "snap_avstand_m"])
        geom = rivers.geometry.iloc[river_idx]

        coords = list(geom.coords)
        start_node, end_node = node_key(coords[0]), node_key(coords[-1])
        proj_dist = geom.project(row.geometry)
        snapped_point = geom.interpolate(proj_dist)
        upstream_partial = substring(geom, 0, proj_dist)

        upstream_idxs = trace_upstream(G, edge_geom, start_node)
        total_length_m = proj_dist + sum(edge_geom[j].length for j in upstream_idxs)

        color = BARRIER_COLORS[row["barrier_category"]]
        segments = [upstream_partial] + [edge_geom[j] for j in upstream_idxs]
        for seg in segments:
            if seg.is_empty or seg.length == 0:
                continue
            features.append({"geometry": seg, "kulvert_id": row["id"], "farge": color, "kategori": row["barrier_category"]})

        snapped_wgs84 = gpd.GeoSeries([snapped_point], crs=WORK_CRS).to_crs("EPSG:4326").iloc[0]
        snap_lon.append(snapped_wgs84.x)
        snap_lat.append(snapped_wgs84.y)
        upstream_km.append(total_length_m / 1000)
        snap_dist_out.append(dist)

    culverts["lon_snappet"] = snap_lon
    culverts["lat_snappet"] = snap_lat
    culverts["snap_avstand_m"] = snap_dist_out
    culverts["oppstrom_lengde_km"] = upstream_km

    n_suspicious = (culverts["snap_avstand_m"] > SUSPICIOUS_SNAP_DISTANCE_M).sum()
    print(f"\n{n_suspicious} culverts snapped more than {SUSPICIOUS_SNAP_DISTANCE_M} m "
          f"away from their nearest river line -- worth a manual look.")
    print(f"Median upstream length unlocked: {culverts['oppstrom_lengde_km'].median():.2f} km")

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    culverts.drop(columns="geometry", errors="ignore").to_csv(OUT_CSV, index=False)
    print(f"Saved {OUT_CSV}")

    lines_gdf = gpd.GeoDataFrame(features, crs=WORK_CRS).to_crs("EPSG:4326")
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": mapping(row.geometry),
                "properties": {
                    "kulvert_id": row["kulvert_id"],
                    "farge": row["farge"],
                    "kategori": row["kategori"],
                },
            }
            for _, row in lines_gdf.iterrows()
        ],
    }
    import json

    with open(OUT_GEOJSON, "w", encoding="utf-8") as f:
        json.dump(geojson, f, ensure_ascii=False)
    print(f"Saved {OUT_GEOJSON}")


if __name__ == "__main__":
    main()
