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
       - a natural waterfall/rapid -- see "Detecting natural barriers"
         below (needs a local elevation raster; skipped if you don't
         have one).
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

Detecting natural barriers (optional, needs an elevation raster)
------------------------------------------------------------------
Pass --dtm pointing at a local "digital terrain model" GeoTIFF (e.g.
from Kartverket's https://hoydedata.no/ download service) to also flag
naturally-impassable stretches of river and stop the upstream walk
there too:

    python scripts/04_koble_til_elvenett.py --river ... --dtm data/raw/dtm/arendal_dtm.tif

The method: for every river segment, we compute the *slope smoothed
over a 100 m stretch of river* centred on it -- not just the segment's
own (sometimes very short, noisy) slope, but the average gradient
across roughly 50 m upstream and 50 m downstream of it too, walking
into neighbouring segments as needed to gather enough length. A reach
this steep is a real obstacle to fish regardless of any culvert:

    >= NATURAL_GRADIENT_CERTAIN (10%)   -> "Sannsynlig naturlig hinder"
                                            (likely a natural barrier;
                                            this DOES stop the upstream
                                            walk, like an Absolutt
                                            culvert)
    >= NATURAL_GRADIENT_CAUTIOUS (7%)   -> "Mulig naturlig hinder"
                                            (flagged on the map for you
                                            to check in the field; does
                                            NOT stop the walk on its
                                            own, since a gradient alone
                                            in this range isn't a
                                            reliable enough signal to
                                            automatically discard
                                            habitat)

Without --dtm, natural-barrier detection is simply skipped (only
man-made Absolutt barriers stop the walk) -- the rest of the script
still works fine.

This part of the script has been validated against a small hand-built
test raster with a known slope in it (see the session notes), not
against a real DTM -- we don't have one for Arendal yet.

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
OUT_NATURAL_GEOJSON = ROOT / "data" / "processed" / "naturlige_hindre.geojson"

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

# Natural-barrier screening: gradient smoothed over this many metres of
# river (roughly half upstream, half downstream of each point), and the
# two thresholds described in the module docstring above.
NATURAL_GRADIENT_WINDOW_M = 100.0
NATURAL_GRADIENT_CERTAIN = 0.10
NATURAL_GRADIENT_CAUTIOUS = 0.07

BLUE = "#2c7fb8"
BARRIER_COLORS = {"Absolutt": "#d7191c", "Partiell": "#fdae61"}
BARRIER_PRIORITY = {"Absolutt": 2, "Partiell": 1}

REVERSE_FLOW_DIRECTION = False  # see the note above


def clean_text(value):
    """Turn pandas' float('nan') for a missing text field into a real
    None, so it doesn't end up serialized as the literal text 'nan'."""
    if value is None or (isinstance(value, float) and value != value):
        return None
    return value


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


def _walk_distance(G, edge_geom, start_edge, start_dist, target_distance, direction):
    """From the point `start_dist` metres along `start_edge` (measured
    from its upstream end), walk `target_distance` metres further
    upstream ('up') or downstream ('down'), following the longest edge
    at any junction (a simple stand-in for "the main channel"). Returns
    (landing_point, distance_actually_covered) -- covered may be less
    than target_distance if the network runs out first."""
    remaining = target_distance
    covered = 0.0
    edge_idx, dist = start_edge, start_dist
    while remaining > 1e-6:
        geom = edge_geom[edge_idx]
        if direction == "up":
            available = dist
            if available >= remaining:
                return geom.interpolate(dist - remaining), covered + remaining
            covered += available
            remaining -= available
            node = node_key(list(geom.coords)[0])
            candidates = [
                (G.get_edge_data(p, node)["idx"], G.get_edge_data(p, node)["length"]) for p in G.predecessors(node)
            ]
            if not candidates:
                return geom.interpolate(0.0), covered
            edge_idx, _ = max(candidates, key=lambda c: c[1])
            dist = edge_geom[edge_idx].length  # enter the new edge at its downstream end
        else:
            available = geom.length - dist
            if available >= remaining:
                return geom.interpolate(dist + remaining), covered + remaining
            covered += available
            remaining -= available
            node = node_key(list(geom.coords)[-1])
            candidates = [
                (G.get_edge_data(node, s)["idx"], G.get_edge_data(node, s)["length"]) for s in G.successors(node)
            ]
            if not candidates:
                return geom.interpolate(geom.length), covered
            edge_idx, _ = max(candidates, key=lambda c: c[1])
            dist = 0.0  # enter the new edge at its upstream end
    return edge_geom[edge_idx].interpolate(dist), covered


def find_natural_barrier_candidates(G, edge_geom, dtm_path):
    """For every edge, the gradient (fraction, positive = downhill
    going downstream) smoothed over NATURAL_GRADIENT_WINDOW_M of river
    centred on the edge's midpoint. For edges already longer than the
    window, this stays entirely within the edge; for shorter edges, it
    walks into neighbouring edges just far enough to make up the
    difference -- never diluting a short, genuinely steep edge by
    tacking on extra length it doesn't need. Returns
    {edge_idx: gradient}."""
    import rasterio

    half_window = NATURAL_GRADIENT_WINDOW_M / 2
    gradients = {}
    with rasterio.open(dtm_path) as src:
        bounds = src.bounds

        def elevation_at(point):
            if not (bounds.left <= point.x <= bounds.right and bounds.bottom <= point.y <= bounds.top):
                return None
            return next(src.sample([(point.x, point.y)]))[0]

        for idx, geom in edge_geom.items():
            mid_dist = geom.length / 2
            up_point, up_covered = _walk_distance(G, edge_geom, idx, mid_dist, half_window, "up")
            down_point, down_covered = _walk_distance(G, edge_geom, idx, mid_dist, half_window, "down")
            z_up, z_down = elevation_at(up_point), elevation_at(down_point)
            total_len = up_covered + down_covered
            if z_up is None or z_down is None or total_len <= 1e-6:
                continue
            gradients[idx] = (z_up - z_down) / total_len
    return gradients


def classify_natural_barriers(gradients, edge_geom, rivers, name_col):
    """Split gradient candidates into the two confidence tiers, and
    return (natural_cut_by_edge, natural_barrier_features):
      - natural_cut_by_edge: {edge_idx: cutoff_m} for the CERTAIN tier
        only -- these act as hard stops in the upstream walk, cut at
        the edge's midpoint (our best estimate of where the steep
        stretch actually is, given we only computed one smoothed
        gradient value per edge, not a fine-grained profile).
      - natural_barrier_features: point features (both tiers) for the
        map to draw an icon at, at each flagged edge's midpoint.
    """
    natural_cut_by_edge = {}
    features = []
    for idx, grad in gradients.items():
        if grad >= NATURAL_GRADIENT_CERTAIN:
            tier = "sikker"
        elif grad >= NATURAL_GRADIENT_CAUTIOUS:
            tier = "mulig"
        else:
            continue
        geom = edge_geom[idx]
        if tier == "sikker":
            natural_cut_by_edge[idx] = geom.length * 0.5
        midpoint = geom.interpolate(0.5, normalized=True)
        midpoint_wgs84 = gpd.GeoSeries([midpoint], crs=WORK_CRS).to_crs("EPSG:4326").iloc[0]
        features.append(
            {
                "type": "Feature",
                "geometry": mapping(midpoint_wgs84),
                "properties": {
                    "tier": tier,
                    "gradient_pct": round(grad * 100, 1),
                    "elvenavn": clean_text(rivers.iloc[idx][name_col] if name_col else None),
                },
            }
        )
    return natural_cut_by_edge, features


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
        help="Optional path to a local elevation raster (GeoTIFF) to detect natural barriers",
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
    name_col = "elvenavn" if "elvenavn" in rivers.columns else None

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
        print(f"Sampling elevation from {args.dtm} to screen for natural barriers ...")
        gradients = find_natural_barrier_candidates(G, edge_geom, args.dtm)
        natural_cut_by_edge, natural_features = classify_natural_barriers(gradients, edge_geom, rivers, name_col)
        n_certain = sum(1 for f in natural_features if f["properties"]["tier"] == "sikker")
        n_cautious = len(natural_features) - n_certain
        print(f"  {n_certain} likely natural barrier(s) (>= {NATURAL_GRADIENT_CERTAIN:.0%}, stops the upstream walk)")
        print(f"  {n_cautious} possible natural barrier(s) (>= {NATURAL_GRADIENT_CAUTIOUS:.0%}, flagged only)")
        with open(OUT_NATURAL_GEOJSON, "w", encoding="utf-8") as f:
            json.dump({"type": "FeatureCollection", "features": natural_features}, f, ensure_ascii=False, default=str)
        print(f"  saved {OUT_NATURAL_GEOJSON}")
    else:
        print("No --dtm given -- skipping natural-barrier screening (only man-made")
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
        Absolutt barrier or likely natural barrier. Returns a list of
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
                        "elvenavn": clean_text(rivers.iloc[idx][name_col] if name_col else None),
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
