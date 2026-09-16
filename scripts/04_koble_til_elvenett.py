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
  2. "Snap" each culvert to the closest point on that river network --
     if an FKB-Vann export is given (--fkb, on by default), and a
     culvert's field coordinate sits closer to an FKB-Vann water feature
     than to any Elvenett line, FKB-Vann's nearer, more precise point is
     used TWICE: as the actual marker position shown on the map (since
     it's the more accurate of the two), and to decide which Elvenett
     edge (and where along it) the upstream walk below starts from --
     the walk itself always needs an actual Elvenett edge, FKB-Vann has
     no equivalent network/flow-direction data. The marker can end up a
     little off the coloured line it's tracing from as a result (the
     same way a raw field coordinate always could be a little off the
     line too -- see SNAP_WARNING_DISTANCE_M) -- but the walk, the
     colouring, and the score are always computed from the SAME
     FKB-Vann-informed point the marker is drawn at, so they can't
     silently drift out of sync with each other the way a purely
     cosmetic override (e.g. done later in step 3) would risk.
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
     and -- if you point --innsjo at NVE's lake data -- also add up the
     surface area of any lakes that stretch reaches, since a lake holds
     far more fish than the same length of stream. These two feed into
     a 0-100 **priority score**: the culvert whose fix would open up
     the most habitat (by both measures) scores 100, relative to the
     other barriers in this run.

     **Exception:** a culvert isn't genuinely a migration barrier ON a
     stream more than SUSPICIOUS_SNAP_DISTANCE_M away from it, so if a
     culvert's Elvenett edge is that far away (input correction from
     FKB-Vann, above, can only pick a better EXISTING edge, it can't
     invent one where the network simply has a gap), it's excluded from
     the walk/colouring entirely: it doesn't colour that distant edge
     red/orange, and it doesn't act as a stop for any OTHER culvert's
     walk either. Its own `oppstrom_lengde_km`, `oppstrom_innsjo_km2`,
     and `prioriteringsscore` are left blank rather than reporting a
     plausible-looking number computed from the wrong, unrelated stream
     -- flagged `score_upalitelig`. It's still a real barrier and still
     shown on the map, just without a fabricated figure or a false
     "blocked" colouring attached to a stream it isn't on.

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

Detecting natural barriers (optional, needs elevation data)
---------------------------------------------------------------
Two ways to get elevation data for this, pick one:

  --dtm path/to/dtm.tif
      A local "digital terrain model" GeoTIFF you already have (e.g.
      downloaded from Kartverket's https://hoydedata.no/ service).
      Works offline once you have the file.

  --hoyde-api
      Uses Kartverket's free point-elevation web service instead (the
      same one step 2 uses) -- no file to download at all, just
      internet access. This works here specifically because we only
      need ~2 elevation samples per river segment (the endpoints of
      each segment's smoothed 100 m window), not a dense grid --
      roughly 1,800 requests for Arendal's 883 segments, comparable to
      what step 2 already does for culvert points. Results are cached
      in data/processed/hoyde_cache_elvenett.json, so a re-run only
      fetches points it doesn't already have.

If neither is given, natural-barrier detection is simply skipped.

    python scripts/04_koble_til_elvenett.py --river ... --dtm data/raw/dtm/arendal_dtm.tif
    # or, no file needed:
    python scripts/04_koble_til_elvenett.py --river ... --hoyde-api

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

Without --dtm or --hoyde-api, natural-barrier detection is simply
skipped (only man-made Absolutt barriers stop the walk) -- the rest of
the script still works fine.

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
import time
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
HOYDE_CACHE_FILE = ROOT / "data" / "processed" / "hoyde_cache_elvenett.json"

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
SUSPICIOUS_SNAP_DISTANCE_M = 50.0

# Purely a diagnostic threshold (does NOT gate score_upalitelig): among
# the culverts more than SUSPICIOUS_SNAP_DISTANCE_M from their Elvenett
# edge, this separates the ones where FKB-Vann confirms real water right
# at the field point (so we're confident it's a real barrier, just on a
# stream Elvenett doesn't map there) from the ones with no such
# confirmation (where the field coordinate itself might simply be off).
# See the console output this feeds.
FKB_CONFIRMS_WATER_DISTANCE_M = 30.0

# Natural-barrier screening: gradient smoothed over this many metres of
# river (roughly half upstream, half downstream of each point), and the
# two thresholds described in the module docstring above.
NATURAL_GRADIENT_WINDOW_M = 100.0
NATURAL_GRADIENT_CERTAIN = 0.10
NATURAL_GRADIENT_CAUTIOUS = 0.07

# The priority score blends two things: how much river length opens up,
# and how much lake surface area opens up (lakes hold a lot more fish
# per unit area than a stream reach, so they're weighted in too, not
# just added to the length in some invented km-per-km2 exchange rate).
# Each is ranked (0-1) among the culverts in this run, then blended by
# this weight. 0.5 means "river length and lake area matter equally";
# raise it to favour culverts that open up lakes more.
LAKE_SCORE_WEIGHT = 0.5

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


def make_raster_elevation_lookup(dtm_path):
    """Elevation lookup backed by a local GeoTIFF (rasterio). Returns
    (elevation_at, cleanup) -- call cleanup() when done to close the
    file."""
    import rasterio

    src = rasterio.open(dtm_path)
    bounds = src.bounds

    def elevation_at(point):
        if not (bounds.left <= point.x <= bounds.right and bounds.bottom <= point.y <= bounds.top):
            return None
        return next(src.sample([(point.x, point.y)]))[0]

    return elevation_at, src.close


def make_api_elevation_lookup(work_crs, cache_path):
    """Elevation lookup backed by Kartverket's free point-elevation web
    service (the same one step 2 uses), so natural-barrier detection
    works without downloading any DTM file at all -- see the "Where to
    get elevation data" note in the module docstring for why this is
    feasible here (a couple of points per river segment, not a dense
    grid). Returns (elevation_at, cleanup) -- cleanup() saves the cache
    to disk and should be called when done (also called periodically
    during the run, so an interrupted run doesn't lose progress)."""
    import requests
    from pyproj import Transformer

    API_URL = "https://ws.geonorge.no/hoydedata/v1/punkt"
    to_wgs84 = Transformer.from_crs(work_crs, "EPSG:4326", always_xy=True)
    session = requests.Session()

    cache = {}
    if cache_path.exists():
        with open(cache_path, "r", encoding="utf-8") as f:
            cache = json.load(f)
    calls_made = 0

    def save_cache():
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache, f)

    def elevation_at(point):
        nonlocal calls_made
        lon, lat = to_wgs84.transform(point.x, point.y)
        key = f"{round(lat, 6)},{round(lon, 6)}"
        if key in cache:
            return cache[key]
        try:
            r = session.get(
                API_URL, params={"nord": lat, "ost": lon, "koordsystemkode": 4326, "geojson": "false"}, timeout=10
            )
            r.raise_for_status()
            punkter = r.json().get("punkter") or []
            z = punkter[0].get("z") if punkter else None
        except Exception as exc:  # noqa: BLE001 - one bad point shouldn't crash the run
            print(f"    Could not fetch height for ({lat}, {lon}): {exc}")
            z = None
        cache[key] = z
        calls_made += 1
        if calls_made % 50 == 0:
            save_cache()
            print(f"    ... {calls_made} elevation points fetched so far")
        time.sleep(0.2)  # be gentle with the free API, same pause step 2 uses
        return z

    return elevation_at, save_cache


def find_natural_barrier_candidates(G, edge_geom, elevation_at):
    """For every edge, the gradient (fraction, positive = downhill
    going downstream) smoothed over NATURAL_GRADIENT_WINDOW_M of river
    centred on the edge's midpoint. For edges already longer than the
    window, this stays entirely within the edge; for shorter edges, it
    walks into neighbouring edges just far enough to make up the
    difference -- never diluting a short, genuinely steep edge by
    tacking on extra length it doesn't need. Returns
    {edge_idx: gradient}. Only 2 elevation lookups per edge (its
    smoothed-window endpoints), so ~2x the number of river segments in
    total -- see make_api_elevation_lookup if you don't have a DTM
    file."""
    half_window = NATURAL_GRADIENT_WINDOW_M / 2
    gradients = {}
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
    parser.add_argument(
        "--hoyde-api",
        action="store_true",
        help=(
            "Detect natural barriers using Kartverket's free elevation API instead of a local "
            "DTM file (needs internet, no download required). Ignored if --dtm is also given."
        ),
    )
    parser.add_argument(
        "--innsjo",
        default=str(ROOT / "data" / "raw" / "nve_innsjo" / "Innsjo_Innsjo.shp"),
        help="Path to NVE's Innsjo (lake) shapefile, used to factor lake area into the priority score",
    )
    parser.add_argument(
        "--fkb",
        default=str(ROOT / "data" / "raw" / "fkb_vann" / "fkb_vann_omrade_arendal.shp"),
        help=(
            "Path to an FKB-Vann export (see step 8). When a culvert's field coordinate sits "
            "closer to an FKB-Vann water feature than to any Elvenett line, that FKB-Vann point "
            "is used as BOTH the displayed marker position (FKB-Vann is positionally more "
            "precise -- aerial photogrammetry vs. a generalised network product) AND the input "
            "for choosing which Elvenett edge the upstream graph walk starts from (Elvenett is "
            "still what the walk itself needs; FKB-Vann has no flow-direction/connectivity data "
            "of its own). Both uses come from the same corrected point, so the walk/colouring/"
            "score can't drift out of sync with where the marker is drawn. Pass an empty string "
            "to disable."
        ),
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

    lakes = None
    innsjo_path = Path(args.innsjo)
    if innsjo_path.exists():
        print(f"Reading lakes from {innsjo_path} ...")
        lakes = gpd.read_file(innsjo_path).to_crs(WORK_CRS)
        print(f"  {len(lakes)} lakes ({lakes['areal_km2'].sum():.2f} km2 total)")
    else:
        print(f"No lake file found at {innsjo_path} -- priority scores will be based on")
        print("river length only (pass --innsjo to also factor in lake area)")

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

    # FKB-Vann-informed correction: if a culvert's field coordinate sits
    # closer to an FKB-Vann water feature than to any Elvenett line, use
    # FKB-Vann's nearest point -- not the raw field coordinate -- as the
    # input for picking which Elvenett edge to snap to. FKB-Vann is
    # positionally more precise, so this fixes cases where the raw GPS
    # point was ambiguous between two nearby streams. The culvert still
    # ends up snapped ONTO Elvenett (needed for the graph walk below);
    # this only improves which edge/point on it gets chosen.
    snap_source = culvert_points.geometry.copy()
    snap_kilde = pd.Series("Elvenett", index=culvert_points.index)
    fkb_avstand_felt = pd.Series(float("nan"), index=culvert_points.index)

    fkb = None
    if args.fkb:
        fkb_path = Path(args.fkb)
        if fkb_path.exists():
            print(f"Reading FKB-Vann from {fkb_path} ...")
            fkb = gpd.read_file(fkb_path).to_crs(WORK_CRS)
            if "objtype" in fkb.columns:
                fkb = fkb[fkb["objtype"] != "Havflate"]
            print(f"  {len(fkb)} water feature(s) (sea excluded)")
        else:
            print(f"No FKB-Vann file found at {fkb_path} -- skipping FKB-Vann-informed snapping")

    if fkb is not None and len(fkb) > 0:
        from shapely.ops import nearest_points

        print("Checking whether FKB-Vann gives a better snap point than the raw field coordinate ...")
        for i, row in culvert_points.iterrows():
            felt_pt = row.geometry
            elvenett_dist = float(nearest.loc[i, "snap_avstand_m"])
            dists = fkb.geometry.distance(felt_pt)
            idx = dists.idxmin()
            fkb_dist = float(dists.loc[idx])
            fkb_avstand_felt.loc[i] = fkb_dist
            if fkb_dist < elvenett_dist:
                _, nearest_pt = nearest_points(felt_pt, fkb.geometry.loc[idx])
                snap_source.loc[i] = nearest_pt
                snap_kilde.loc[i] = "FKB-Vann"

        corrected_idx = snap_kilde[snap_kilde == "FKB-Vann"].index
        print(f"  {len(corrected_idx)} of {len(culvert_points)} culvert(s) will snap via an FKB-Vann-corrected point")
        if len(corrected_idx) > 0:
            corrected_points = gpd.GeoDataFrame(geometry=snap_source.loc[corrected_idx], crs=WORK_CRS)
            nearest_corrected = gpd.sjoin_nearest(
                corrected_points, rivers[["geometry"]], distance_col="snap_avstand_m_korrigert", how="left"
            )
            nearest_corrected = nearest_corrected[~nearest_corrected.index.duplicated(keep="first")]
            nearest.loc[corrected_idx, "index_right"] = nearest_corrected["index_right"]

    natural_cut_by_edge = {}
    elevation_at, cleanup_elevation = None, None
    if args.dtm:
        print(f"Sampling elevation from {args.dtm} to screen for natural barriers ...")
        elevation_at, cleanup_elevation = make_raster_elevation_lookup(args.dtm)
    elif args.hoyde_api:
        print("Using Kartverket's elevation API to screen for natural barriers")
        print("(needs internet; ~2 requests per river segment, cached to disk) ...")
        elevation_at, cleanup_elevation = make_api_elevation_lookup(WORK_CRS, HOYDE_CACHE_FILE)

    if elevation_at is not None:
        gradients = find_natural_barrier_candidates(G, edge_geom, elevation_at)
        cleanup_elevation()
        natural_cut_by_edge, natural_features = classify_natural_barriers(gradients, edge_geom, rivers, name_col)
        n_certain = sum(1 for f in natural_features if f["properties"]["tier"] == "sikker")
        n_cautious = len(natural_features) - n_certain
        print(f"  {n_certain} likely natural barrier(s) (>= {NATURAL_GRADIENT_CERTAIN:.0%}, stops the upstream walk)")
        print(f"  {n_cautious} possible natural barrier(s) (>= {NATURAL_GRADIENT_CAUTIOUS:.0%}, flagged only)")
        with open(OUT_NATURAL_GEOJSON, "w", encoding="utf-8") as f:
            json.dump({"type": "FeatureCollection", "features": natural_features}, f, ensure_ascii=False, default=str)
        print(f"  saved {OUT_NATURAL_GEOJSON}")
    else:
        print("No --dtm or --hoyde-api given -- skipping natural-barrier screening")
        print("(only man-made Absolutt barriers will stop the upstream walk).")

    # Snap position (edge + distance-from-upstream-end) for every
    # processed culvert, keyed by row index, plus a lookup of which
    # Absolutt-barrier snap points sit on which edge (used to stop
    # OTHER culverts' upstream walks).
    snap_edge, snap_proj, elvenett_point_by_i = {}, {}, {}
    elvenett_avstand = pd.Series(float("nan"), index=culvert_points.index)
    absolutt_cuts_by_edge = {}
    for i, row in culvert_points.iterrows():
        river_idx = int(nearest.loc[i, "index_right"])
        geom = rivers.geometry.iloc[river_idx]
        # Project the snap SOURCE point (the FKB-Vann-corrected point when
        # applicable, otherwise the raw field point) -- not always the raw
        # field point -- so a corrected culvert lands at the spot along
        # this edge nearest its true (FKB-informed) position.
        proj_dist = geom.project(snap_source.loc[i])
        snap_edge[i] = river_idx
        snap_proj[i] = proj_dist
        elvenett_point = geom.interpolate(proj_dist)
        elvenett_point_by_i[i] = elvenett_point
        elvenett_avstand.loc[i] = row.geometry.distance(elvenett_point)
        # A culvert whose nearest Elvenett edge is this far away isn't
        # genuinely ON that stream (see SUSPICIOUS_SNAP_DISTANCE_M) --
        # so it shouldn't be able to act as a barrier THAT stream is
        # blocked by, any more than we'd compute ITS OWN upstream reach
        # from that unrelated edge (see the score_upalitelig handling
        # below). Simply not registering it here means other culverts'
        # walks pass straight through, and its own walk (below) reaches
        # nothing worth colouring on that edge either.
        if row["barrier_category"] == "Absolutt" and elvenett_avstand.loc[i] <= SUSPICIOUS_SNAP_DISTANCE_M:
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
    upstream_km, upstream_lake_km2, snap_dist_out, snap_lon, snap_lat = [], [], [], [], []
    edge_intervals = {}  # edge_idx -> list of (start, end, priority)

    for i, row in culvert_points.iterrows():
        # A culvert whose Elvenett edge is more than SUSPICIOUS_SNAP_DISTANCE_M
        # away isn't genuinely ON that stream (see the note where
        # absolutt_cuts_by_edge is built above) -- so its own walk
        # shouldn't colour that distant, likely-unrelated edge as
        # "blocked" either, even though we still trace it (below) purely
        # to know how far it reaches, for diagnostics.
        on_elvenett = elvenett_avstand.loc[i] <= SUSPICIOUS_SNAP_DISTANCE_M
        pieces, total_length_m = trace_upstream(i)
        category = row["barrier_category"]
        priority = BARRIER_PRIORITY[category]
        if on_elvenett:
            for edge_idx, s, e in pieces:
                edge_intervals.setdefault(edge_idx, []).append((s, e, priority))

        lake_km2 = 0.0
        if on_elvenett and lakes is not None and pieces:
            piece_geoms = [substring(edge_geom[edge_idx], s, e) for edge_idx, s, e in pieces]
            piece_geoms = [g for g in piece_geoms if not g.is_empty]
            if piece_geoms:
                reachable_union = piece_geoms[0] if len(piece_geoms) == 1 else gpd.GeoSeries(piece_geoms).union_all()
                touching = lakes[lakes.geometry.intersects(reachable_union)]
                lake_km2 = float(touching["areal_km2"].sum())
        upstream_lake_km2.append(lake_km2)

        # The point used for the GRAPH WALK above is always on Elvenett
        # (the network needs an actual edge to trace from) -- already
        # computed above as elvenett_point_by_i/elvenett_avstand.
        elvenett_point = elvenett_point_by_i[i]

        # The point we DISPLAY is different: when FKB-Vann informed this
        # culvert's snap, show it at FKB-Vann's own point -- the more
        # precise, more accurate location -- rather than pulling it back
        # onto the (less precise) Elvenett line just to sit exactly on
        # the drawn network. A few metres/tens of metres between the dot
        # and the coloured line it's tracing from is expected and
        # honest, the same way the original raw-field-coordinate snap
        # always could be a little off the line too (see
        # SNAP_WARNING_DISTANCE_M).
        display_point = snap_source.loc[i] if snap_kilde.loc[i] == "FKB-Vann" else elvenett_point
        display_wgs84 = gpd.GeoSeries([display_point], crs=WORK_CRS).to_crs("EPSG:4326").iloc[0]
        snap_lon.append(display_wgs84.x)
        snap_lat.append(display_wgs84.y)
        upstream_km.append(total_length_m / 1000)
        # The distance that actually matters for "how far is the marker
        # from where the surveyor stood": from the ORIGINAL field point
        # to the final displayed point.
        snap_dist_out.append(float(row.geometry.distance(display_point)))

    culverts["lon_snappet"] = snap_lon
    culverts["lat_snappet"] = snap_lat
    culverts["snap_avstand_m"] = snap_dist_out
    culverts["elvenett_avstand_m"] = elvenett_avstand.values
    culverts["snap_kilde"] = snap_kilde.values
    culverts["fkb_avstand_felt_m"] = fkb_avstand_felt.values
    # NOTE: deliberately checks elvenett_avstand_m here, not
    # snap_avstand_m -- snap_avstand_m is "how far is the MARKER from
    # the field point" (small for an FKB-Vann-placed marker, by
    # construction), but what determines whether the trace/score can be
    # trusted is "how far is the ELVENETT EDGE we're tracing from" --
    # those are different questions once the marker can sit at FKB-Vann's
    # point instead of on the Elvenett line itself. A culvert simply
    # isn't a migration barrier ON a stream more than
    # SUSPICIOUS_SNAP_DISTANCE_M away from it, full stop -- regardless of
    # whether FKB-Vann happens to confirm real water nearby or not, so
    # this no longer requires that extra condition (it did in an earlier
    # version of this script; FKB_CONFIRMS_WATER_DISTANCE_M is kept only
    # as a separate diagnostic, see fkb_avstand_felt_m below).
    culverts["score_upalitelig"] = culverts["elvenett_avstand_m"] > SUSPICIOUS_SNAP_DISTANCE_M
    culverts["oppstrom_lengde_km"] = upstream_km
    culverts["oppstrom_innsjo_km2"] = upstream_lake_km2

    # score_upalitelig culverts aren't genuinely ON the Elvenett edge
    # they'd otherwise trace from (it's more than SUSPICIOUS_SNAP_DISTANCE_M
    # away) -- already excluded above from colouring the network and from
    # acting as a stop for other culverts' walks. Blank their own
    # "reachable habitat" figures too, for the same reason: they don't
    # actually describe a stream this culvert is a barrier on. The
    # priority score below inherits the blank automatically since it's
    # ranked from these two columns.
    culverts.loc[culverts["score_upalitelig"], ["oppstrom_lengde_km", "oppstrom_innsjo_km2"]] = float("nan")

    # Priority score: rank each culvert on river length opened up AND
    # lake area opened up (0-1 each), then blend the two -- rather than
    # inventing a km-per-km2 exchange rate between "river" and "lake",
    # which we have no real basis for. 100 = ranks at or near the top
    # on the blended measure among the barriers processed in this run.
    # rank() leaves NaN as NaN (na_option="keep", the default), so a
    # blanked-out culvert above gets a blank score too, not a rank
    # among values that aren't really comparable to it.
    score_river = culverts["oppstrom_lengde_km"].rank(pct=True, method="average")
    if lakes is not None:
        score_lake = culverts["oppstrom_innsjo_km2"].rank(pct=True, method="average")
        blended = LAKE_SCORE_WEIGHT * score_lake + (1 - LAKE_SCORE_WEIGHT) * score_river
    else:
        blended = score_river
    culverts["prioriteringsscore"] = (blended * 100).round().astype("Int64")

    n_suspicious = (culverts["snap_avstand_m"] > SUSPICIOUS_SNAP_DISTANCE_M).sum()
    print(f"\n{n_suspicious} culverts placed (marker position) more than "
          f"{SUSPICIOUS_SNAP_DISTANCE_M:.0f} m from their field coordinate -- worth a manual look.")
    n_unreliable = int(culverts["score_upalitelig"].sum())
    print(
        f"{n_unreliable} culverts are more than {SUSPICIOUS_SNAP_DISTANCE_M:.0f} m from the "
        f"Elvenett edge they'd otherwise trace from -- not genuinely a migration barrier on that "
        f"stream, so they don't colour it, don't stop other culverts' walks on it, and get no "
        f"oppstrom_lengde_km/oppstrom_innsjo_km2/prioriteringsscore of their own (flagged "
        f"score_upalitelig=True) rather than a number computed from the wrong, unrelated stream."
    )
    n_fkb_confirmed = int(
        (culverts["score_upalitelig"] & (culverts["fkb_avstand_felt_m"] < FKB_CONFIRMS_WATER_DISTANCE_M)).sum()
    )
    if n_fkb_confirmed:
        print(
            f"  {n_fkb_confirmed} of those have FKB-Vann confirming real water within "
            f"{FKB_CONFIRMS_WATER_DISTANCE_M:.0f} m of the field point (so we're confident these "
            f"really are barriers, just on a stream Elvenett doesn't map there) -- the other "
            f"{n_unreliable - n_fkb_confirmed} have no such confirmation either, so it's also "
            f"possible the field coordinate itself is simply off."
        )
    print(f"Median upstream length unlocked: {culverts['oppstrom_lengde_km'].median():.2f} km")
    if lakes is not None:
        n_with_lake = (culverts["oppstrom_innsjo_km2"] > 0).sum()
        print(f"{n_with_lake} of {len(culverts)} culverts have a lake somewhere upstream "
              f"(total {culverts['oppstrom_innsjo_km2'].sum():.2f} km2 across all of them)")

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
