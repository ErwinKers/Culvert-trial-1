"""
Step 4: snap each culvert onto the real river network, then work out
-- precisely, stopping where fish genuinely can't get any further --
how much of the river network upstream of each barrier would actually
become reachable if that barrier were fixed.

Why we need this
-----------------
The culvert coordinates in the spreadsheet aren't perfectly precise
(they were taken in the field, often with a handheld GPS). If we just
trust the raw coordinate, a culvert might appear to sit a few metres off
to the side of the actual stream. So instead we:

  1. Load NVE's "Elvenett" (river network) data -- the same official
     river/stream map data NVE itself uses. Unlike the background map
     tiles from step 3, this is real *line geometry* (actual coordinates
     for every stream/river), which lets us do real spatial analysis.
  2. "Snap" each culvert to the closest point on that river network.
  3. Walk UPSTREAM through the river network graph from that snapped
     point, collecting every stream segment that eventually flows
     into it -- but STOP walking further up any branch as soon as we
     hit something fish can't get past anyway:
       - another "Absolutt" (total) barrier culvert further upstream on
         the same branch -- fixing the lower culvert wouldn't matter if
         there's still a total blockage above it, or
       - a natural waterfall/rapid: if the ground drops more than
         NATURAL_BARRIER_DROP_M within NATURAL_BARRIER_WINDOW_M of
         river length, most fish species can't climb that regardless of
         any culvert (needs a local elevation raster -- see below; this
         part is skipped if you don't have one).
     A "Partiell" (partial) barrier upstream does NOT stop the walk,
     since fish can still get through it at least some of the time.
  4. Colour the network based on that: red = upstream of (and not
     blocked before reaching) an Absolutt barrier, orange = same but
     for a Partiell barrier (red wins if both apply), blue = everything
     else. Each river segment is split exactly at every culvert/barrier
     point, so the colouring lines up precisely with where the barriers
     actually are -- no bleeding into the stretch downstream of a
     barrier just because that happened to be part of the same mapped
     line.
  5. Add up the (correctly stopped) upstream length in km per culvert,
     and turn that into a 0-100 **priority score**: the culvert whose
     fix would open up the most habitat scores 100, relative to the
     other barriers in this run.

Only culverts assessed as "Absolutt" (total barrier) or "Partiell"
(partial barrier) count as barriers here.

This script only processes ONE municipality (kommune) at a time --
--kommune, default "Arendal" -- matching the coverage of the river
network file.

Where the river data comes from
--------------------------------
NVE's "Elvenett" is a proper *topological network*: every confluence
is a break point between two line features, and lines are digitized in
the direction of flow (the first point of a line is upstream, the last
point is downstream).

    python scripts/04_koble_til_elvenett.py --river data/raw/nve_elvenett/Elv_Elvenett.shp --kommune Arendal

Optional: detecting natural waterfalls/rapids
-----------------------------------------------
Pass --dtm pointing at a local elevation raster (a GeoTIFF "digital
terrain model", e.g. from Kartverket's https://hoydedata.no/ download
service) to also detect natural barriers along the river and stop the
upstream walk there too:

    python scripts/04_koble_til_elvenett.py --river ... --dtm data/raw/dtm/arendal_dtm.tif

Without --dtm, this step is simply skipped (only man-made Absolutt
barriers stop the walk) -- the rest of the script still works fine.

IMPORTANT -- please sanity-check the flow direction once
----------------------------------------------------------
This script assumes NVE's Elvenett lines are digitized from upstream to
downstream. Before trusting the results, do a quick manual check on the
generated map: confirm the highlighted "upstream" stretch of a river
you know is actually upstream of the barrier, not downstream. If it's
backwards, flip REVERSE_FLOW_DIRECTION below and re-run.
"""

import argparse
import json
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
from shapely.geometry import mapping
from shapely.ops import substring

ROOT = Path(__file__).resolve().parent.parent
IN_CSV_CANDIDATES = [
    ROOT / "data" / "processed" / "kulvert_punkter_med_hoyde.csv",
    ROOT / "data" / "processed" / "kulvert_punkter.csv",
]
OUT_CSV = ROOT / "data" / "processed" / "kulvert_punkter_oppstrom.csv"
OUT_GEOJSON = ROOT / "data" / "processed" / "elvenett_farget.geojson"

# A projected, metre-based coordinate system to do the distance/length
# math in (this matches the CRS NVE delivers Elvenett in).
WORK_CRS = "EPSG:32632"

# Two points closer than this (in the graph-node sense) are treated as
# the same confluence point, to absorb tiny floating-point differences
# in how the shared endpoint was stored in each line.
NODE_SNAP_TOLERANCE_M = 1.0

# A culvert whose nearest river point is farther away than this is
# probably not actually matched to the right stream -- we still snap
# it (nothing better to do), but flag it so you can review it.
SUSPICIOUS_SNAP_DISTANCE_M = 100.0

# "Natural barrier" rule of thumb: most anadromous fish can't climb a
# drop bigger than this within this short a stretch of river.
NATURAL_BARRIER_DROP_M = 2.0
NATURAL_BARRIER_WINDOW_M = 5.0
# How finely to sample the river's elevation profile when looking for
# such drops (only used when --dtm is given).
DTM_SAMPLE_SPACING_M = 2.0

BLUE = "#2c7fb8"
BARRIER_COLORS = {"Absolutt": "#d7191c", "Partiell": "#fdae61"}
BARRIER_PRIORITY = {"Absolutt": 2, "Partiell": 1}

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


def find_natural_barriers(edge_geom, dtm_path):
    """Sample each river line's elevation profile from a local raster
    and flag the point where the steepest short drop happens, if it
    exceeds our fish-passable threshold. Returns {edge_idx: distance
    along the edge (from its upstream end) of the barrier}, keeping
    only the most-downstream such point per edge (the first one a fish
    swimming upstream would actually meet)."""
    import rasterio

    natural_cut_by_edge = {}
    with rasterio.open(dtm_path) as src:
        raster_bounds = src.bounds
        for idx, geom in edge_geom.items():
            length = geom.length
            if length < DTM_SAMPLE_SPACING_M:
                continue
            n_samples = max(2, int(length // DTM_SAMPLE_SPACING_M) + 1)
            dists = np.linspace(0, length, n_samples)
            coords = [(p.x, p.y) for p in (geom.interpolate(d) for d in dists)]
            if not (raster_bounds.left <= coords[0][0] <= raster_bounds.right):
                continue  # this edge is outside the DTM's coverage
            elevs = np.array([v[0] for v in src.sample(coords)], dtype=float)

            worst_dist = None
            for i in range(n_samples):
                j = i
                while j + 1 < n_samples and dists[j + 1] - dists[i] <= NATURAL_BARRIER_WINDOW_M:
                    j += 1
                if j == i:
                    continue
                drop = elevs[i] - elevs[j]  # positive = elevation falls going downstream
                if drop >= NATURAL_BARRIER_DROP_M:
                    # Keep the most-downstream (largest-distance) barrier
                    # start point found on this edge.
                    if worst_dist is None or dists[i] > worst_dist:
                        worst_dist = dists[i]
            if worst_dist is not None:
                natural_cut_by_edge[idx] = worst_dist
    return natural_cut_by_edge


def resolve_edge_coloring(length, intervals):
    """intervals: list of (start_m, end_m, priority). Returns a list of
    (start_m, end_m, color) covering the whole [0, length] edge, with
    overlaps resolved by taking the highest priority at each point."""
    if not intervals:
        return [(0.0, length, BLUE)]

    breakpoints = sorted({0.0, length, *(p for iv in intervals for p in (iv[0], iv[1]))})
    pieces = []
    for a, b in zip(breakpoints, breakpoints[1:]):
        if b - a <= 1e-9:
            continue
        mid = (a + b) / 2
        best_priority = 0
        for s, e, p in intervals:
            if s <= mid <= e and p > best_priority:
                best_priority = p
        color = {2: BARRIER_COLORS["Absolutt"], 1: BARRIER_COLORS["Partiell"], 0: BLUE}[best_priority]
        pieces.append((a, b, color))

    merged = []
    for a, b, color in pieces:
        if merged and merged[-1][2] == color and abs(merged[-1][1] - a) < 1e-6:
            merged[-1] = (merged[-1][0], b, color)
        else:
            merged.append((a, b, color))
    return merged


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--river",
        default=str(ROOT / "data" / "raw" / "nve_elvenett" / "Elv_Elvenett.shp"),
        help="Path to the NVE Elvenett .shp file",
    )
    parser.add_argument(
        "--kommune",
        default="Arendal",
        help="Only process culverts in this kommune (must match the river file's coverage)",
    )
    parser.add_argument(
        "--dtm",
        default=None,
        help="Optional path to a local elevation raster (GeoTIFF) to detect natural waterfalls/rapids",
    )
    args = parser.parse_args()

    river_path = Path(args.river)
    if not river_path.exists():
        print(f"Could not find river shapefile at {river_path}")
        print("Place the 'Elv' folder (Elv_Elvenett.shp/.shx/.dbf/.prj) from")
        print("your NVE map data export there, or pass --river.")
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
    all_culverts = pd.read_csv(culvert_csv)
    culverts = all_culverts[
        (all_culverts["kommune"] == args.kommune)
        & (all_culverts["barrier_category"].isin(BARRIER_COLORS.keys()))
    ].copy()
    print(f"  {len(culverts)} culverts in {args.kommune} are Absolutt/Partiell and will be processed")
    if len(culverts) == 0:
        raise SystemExit(f"No Absolutt/Partiell culverts found for kommune='{args.kommune}'.")

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
    nearest = nearest[~nearest.index.duplicated(keep="first")]  # exact ties -> keep first

    natural_cut_by_edge = {}
    if args.dtm:
        print(f"Sampling elevation from {args.dtm} to look for natural barriers ...")
        natural_cut_by_edge = find_natural_barriers(edge_geom, args.dtm)
        print(f"  found {len(natural_cut_by_edge)} natural-barrier candidate(s)")
    else:
        print("No --dtm given -- skipping natural-barrier detection (only man-made")
        print("Absolutt barriers will stop the upstream walk).")

    # Snap position (edge + distance-from-upstream-end) for every
    # processed culvert, keyed by row index, plus a lookup of which
    # Absolutt-barrier snap points sit on which edge (used to stop
    # OTHER culverts' upstream walks).
    snap_edge, snap_proj = {}, {}
    absolutt_cuts_by_edge = {}
    for i, row in culvert_points.iterrows():
        river_idx = int(nearest.loc[i, "index_right"])
        geom = rivers.geometry.iloc[river_idx]
        proj_dist = geom.project(row.geometry)
        snap_edge[i] = river_idx
        snap_proj[i] = proj_dist
        if row["barrier_category"] == "Absolutt":
            absolutt_cuts_by_edge.setdefault(river_idx, []).append((i, proj_dist))

    def stops_on_edge(edge_idx, exclude_culvert_i):
        stops = [d for cid, d in absolutt_cuts_by_edge.get(edge_idx, []) if cid != exclude_culvert_i]
        if edge_idx in natural_cut_by_edge:
            stops.append(natural_cut_by_edge[edge_idx])
        return stops

    def trace_upstream(source_i):
        """Walk upstream from culvert source_i, stopping at any other
        Absolutt barrier or natural barrier. Returns a list of
        (edge_idx, start_m, end_m) pieces that remain reachable, and
        their total length in metres."""
        pieces = []
        total_length = 0.0
        visited_edges = set()
        # stack entries: (edge_idx, entry_dist_along_edge, is_source_edge)
        stack = [(snap_edge[source_i], snap_proj[source_i], True)]
        while stack:
            edge_idx, entry_dist, is_source = stack.pop()
            if edge_idx in visited_edges:
                continue
            visited_edges.add(edge_idx)

            exclude = source_i if is_source else None
            stops = [d for d in stops_on_edge(edge_idx, exclude) if d < entry_dist]
            if stops:
                cutoff = max(stops)
                if entry_dist - cutoff > 1e-9:
                    pieces.append((edge_idx, cutoff, entry_dist))
                    total_length += entry_dist - cutoff
                continue  # blocked -- do not walk further up this branch

            if entry_dist > 1e-9:
                pieces.append((edge_idx, 0.0, entry_dist))
                total_length += entry_dist

            start_node = node_key(list(edge_geom[edge_idx].coords)[0])
            for pred in G.predecessors(start_node):
                pred_edge = G.get_edge_data(pred, start_node)["idx"]
                stack.append((pred_edge, edge_geom[pred_edge].length, False))

        return pieces, total_length

    print("Tracing upstream from each culvert (stopping at other barriers) ...")
    upstream_km, snap_dist_out, snap_lon, snap_lat = [], [], [], []
    edge_intervals = {}  # edge_idx -> list of (start, end, priority)

    for i, row in culvert_points.iterrows():
        pieces, total_length_m = trace_upstream(i)
        category = row["barrier_category"]
        priority = BARRIER_PRIORITY[category]
        for edge_idx, s, e in pieces:
            edge_intervals.setdefault(edge_idx, []).append((s, e, priority))

        geom = rivers.geometry.iloc[snap_edge[i]]
        snapped_point = geom.interpolate(snap_proj[i])
        snapped_wgs84 = gpd.GeoSeries([snapped_point], crs=WORK_CRS).to_crs("EPSG:4326").iloc[0]
        snap_lon.append(snapped_wgs84.x)
        snap_lat.append(snapped_wgs84.y)
        upstream_km.append(total_length_m / 1000)
        snap_dist_out.append(float(nearest.loc[i, "snap_avstand_m"]))

    culverts["lon_snappet"] = snap_lon
    culverts["lat_snappet"] = snap_lat
    culverts["snap_avstand_m"] = snap_dist_out
    culverts["oppstrom_lengde_km"] = upstream_km
    # Priority score: 100 = the culvert that would open up the most
    # habitat of all the barriers processed in this run, 0 = the least.
    culverts["prioriteringsscore"] = (
        culverts["oppstrom_lengde_km"].rank(pct=True, method="average") * 100
    ).round().astype(int)

    n_suspicious = (culverts["snap_avstand_m"] > SUSPICIOUS_SNAP_DISTANCE_M).sum()
    print(f"\n{n_suspicious} culverts snapped more than {SUSPICIOUS_SNAP_DISTANCE_M} m "
          f"away from their nearest river line -- worth a manual look.")
    print(f"Median upstream length unlocked: {culverts['oppstrom_lengde_km'].median():.2f} km")

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    culverts.drop(columns="geometry", errors="ignore").to_csv(OUT_CSV, index=False)
    print(f"Saved {OUT_CSV}")

    print("Building the coloured river network for the map ...")
    name_col = "elvenavn" if "elvenavn" in rivers.columns else None
    features = []
    n_red = n_orange = n_blue = 0
    for idx, geom in edge_geom.items():
        for a, b, color in resolve_edge_coloring(geom.length, edge_intervals.get(idx, [])):
            piece = substring(geom, a, b)
            if piece.is_empty or piece.length == 0:
                continue
            piece_wgs84 = gpd.GeoSeries([piece], crs=WORK_CRS).to_crs("EPSG:4326").iloc[0]
            features.append(
                {
                    "type": "Feature",
                    "geometry": mapping(piece_wgs84),
                    "properties": {
                        "farge": color,
                        "elvenavn": (rivers.iloc[idx][name_col] if name_col else None),
                    },
                }
            )
            if color == BARRIER_COLORS["Absolutt"]:
                n_red += 1
            elif color == BARRIER_COLORS["Partiell"]:
                n_orange += 1
            else:
                n_blue += 1
    print(f"River pieces: {n_red} red, {n_orange} orange, {n_blue} blue")

    geojson = {"type": "FeatureCollection", "features": features}
    with open(OUT_GEOJSON, "w", encoding="utf-8") as f:
        json.dump(geojson, f, ensure_ascii=False, default=str)
    print(f"Saved {OUT_GEOJSON}")


if __name__ == "__main__":
    main()
