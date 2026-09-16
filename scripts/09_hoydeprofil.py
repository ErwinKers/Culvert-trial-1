"""
Step 9 (optional): a height profile of one whole vassdrag, with candidate
"foss" (natural waterfall/rapid) locations marked.

Why this exists
----------------
Step 4 already detects natural barriers, but only as a single smoothed
gradient value per short river segment -- good for deciding whether to
stop the upstream walk at that segment, but not something you can look
at and sanity-check against what you already know about a real river.
This script is for exactly that: pick a whole named vassdrag (river
system), walk its main stem from mouth to source, and draw an actual
elevation profile -- the kind of chart you can eyeball and say "yes,
that drop at km 6 matches the waterfall I know is there" or "that's not
right." It uses the *same* thresholds already validated in step 4
(NATURAL_GRADIENT_CERTAIN = 10%, NATURAL_GRADIENT_CAUTIOUS = 7%, smoothed
over the same NATURAL_GRADIENT_WINDOW_M = 100 m) -- this is a different
view of the same method, not a new one.

Finding "the whole river" from the data
-----------------------------------------
NVE's Elvenett only gives a plain name (`elvenavn`) to a minority of
segments (211 of 883 for Arendal) -- filtering on that alone can leave
gaps (checked directly: for "Arendalsvassdraget" it splits into two
disconnected pieces, because some connecting stretches carry a
different name or none at all). The `hierarki` field is more complete
(groups a segment into the whole vassdrag it belongs to, e.g.
"Rore/Arendalsvassdraget"), but matching it pulls in every tributary,
not just the main channel -- a tree, not a single line.

So this script: filters to every segment whose `hierarki` contains the
given name, builds a graph over just those segments, finds the real
MOUTH (the one node nothing flows out of, per Elvenett's own
upstream->downstream digitisation order -- same convention
`REVERSE_FLOW_DIRECTION` relies on in step 4), and takes the longest
path FROM that mouth to whichever node ends up farthest away. This
reliably picks out the main stem from mouth to furthest headwater,
correctly bridging any naming gaps.

An earlier version of this found the longest path between ANY two
points instead (the graph's "diameter"), trusting only total length and
not digitisation direction at all. That's a real bug, not a simplification:
for a branching river, the two farthest-apart points are just as likely
to be two DIFFERENT headwater tributaries as they are to include the
actual mouth -- producing a "profile" that walks down one tributary to
a shared confluence and back UP an unrelated one, which no real river
does (caught by the project owner eyeballing the very first real chart:
an impossible up-down-up shape). Anchoring at the real mouth and only
ever walking upstream from there fixes this by construction: the result
is always one genuine downstream<->upstream line. (Checked directly for
Arendalsvassdraget: 487 segments matched, 26 disconnected pieces
correctly excluded, main stem 12.6 km through 44 segments -- a sensible
main-stem length, and the real elevation run confirms it's monotonic.)

Where to get elevation, and which is most precise
---------------------------------------------------
Two options, same as step 4:

- `--dtm path/to/dtm.tif` -- Kartverket's actual national terrain model
  ("Nasjonal detaljert hoydemodell"), downloaded as a GeoTIFF from
  https://hoydedata.no/. THIS IS THE MOST PRECISE OPTION: nationally
  it's a 1x1 m laser-scanned grid (locally even finer in some surveyed
  projects), and reading a downloaded raster directly lets you sample
  as densely as you want along the river for free, with no round trip
  per point. Recommended for this script, since a ~15-20 km river at a
  useful sampling interval is a few hundred points.
- `--hoyde-api` -- Kartverket's free point-elevation web service
  (`ws.geonorge.no/hoydedata/v1/punkt`) -- queries the *same* underlying
  national height model, one point at a time, over the internet. Fine
  for this script's point count, just slower and needs a live
  connection; use it if you don't want to download a DTM file.

**Now run for real with `--hoyde-api`** (this project's original build
environment had no route to Kartverket's services; a real run also
caught and fixed a wrong API parameter name -- see the elevation
discussion in the README -- and the mouth-finding bug described above).
`--dtm` itself hasn't been tried against a real downloaded raster yet,
only `--hoyde-api`; if you get a DTM file, it's worth running as a
cross-check.

Usage
-----
    python scripts/09_hoydeprofil.py --dtm path/to/dtm.tif --vassdrag Arendalsvassdraget
    python scripts/09_hoydeprofil.py --hoyde-api --vassdrag Arendalsvassdraget
"""

import argparse
import json
import re
import time
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import networkx as nx
from shapely.geometry import LineString
from shapely.ops import linemerge

ROOT = Path(__file__).resolve().parent.parent
HOYDE_CACHE_FILE = ROOT / "data" / "processed" / "hoyde_cache_profil.json"

# Same CRS and thresholds as step 4 -- kept identical on purpose, this
# is the same method applied to a whole river instead of per-segment.
WORK_CRS = "EPSG:32632"
NATURAL_GRADIENT_WINDOW_M = 100.0
NATURAL_GRADIENT_CERTAIN = 0.10
NATURAL_GRADIENT_CAUTIOUS = 0.07

SAMPLE_INTERVAL_M = 50.0

# Same assumption, and same caveat, as 04_koble_til_elvenett.py: NVE
# digitizes Elvenett lines upstream -> downstream. Keep these two
# scripts' setting in sync -- if step 4 needed this flipped for your
# river data, step 9 needs the same flip.
REVERSE_FLOW_DIRECTION = False


def node_key(coord):
    return (round(coord[0], 1), round(coord[1], 1))


def find_main_stem(rivers, vassdrag):
    match = rivers["hierarki"].astype(str).str.contains(re.escape(vassdrag), case=False, na=False)
    sub = rivers[match]
    if len(sub) == 0:
        print(f"No segments found with '{vassdrag}' in the hierarki field.")
        print(f"Values seen: {sorted(rivers['hierarki'].dropna().unique().tolist())}")
        raise SystemExit(1)
    print(f"  {len(sub)} segments matched '{vassdrag}' in hierarki ({sub['elvelengde'].sum()/1000:.1f} km total)")

    # Undirected graph G (just to find the connected component) and a
    # DIRECTED graph D that respects NVE's upstream->downstream
    # digitisation order (same convention as step 4's build_graph).
    #
    # The previous version of this function found the graph's DIAMETER
    # (longest path between ANY two nodes) using undirected distances --
    # which, for a branching river tree, is just as likely to run
    # between two DIFFERENT headwater tributaries as it is to include
    # the actual mouth. The resulting "profile" would walk down one
    # tributary to a shared confluence and then back UP a completely
    # unrelated tributary -- exactly the impossible up-then-down-then-
    # up-again shape a real river can never have, since water from two
    # separate tributaries never flows from one into the other, only
    # both into what's downstream of their confluence. Anchoring the
    # walk at the real mouth (identified from flow direction, not
    # picked arbitrarily) and only ever going upstream from there fixes
    # this: the result is always one genuine downstream-to-upstream
    # line, by construction.
    G = nx.Graph()
    D = nx.DiGraph()
    for idx, geom, length in zip(sub.index, sub.geometry, sub["elvelengde"]):
        coords = list(geom.coords)
        if REVERSE_FLOW_DIRECTION:
            coords = coords[::-1]
        a, b = node_key(coords[0]), node_key(coords[-1])  # a = upstream end, b = downstream end
        stored_geom = LineString(coords)
        G.add_edge(a, b, idx=idx, geometry=stored_geom, length=length)
        D.add_edge(a, b, idx=idx, geometry=stored_geom, length=length)

    components = list(nx.connected_components(G))
    if len(components) > 1:
        print(
            f"  WARNING: {len(components)} disconnected piece(s) found within this vassdrag's "
            f"segments -- using the largest ({max(len(c) for c in components)} of "
            f"{sum(len(c) for c in components)} nodes). A smaller piece is either a separate "
            f"sub-catchment or a mapping gap; not included in this profile."
        )
    biggest = max(components, key=len)
    Gc = G.subgraph(biggest)
    Dc = D.subgraph(biggest)

    # The mouth is the one node nothing flows OUT of within this
    # vassdrag (out-degree 0 in the directed graph) -- for a proper
    # dendritic (non-braided) river tree with consistent digitisation
    # direction, there should be exactly one. If more than one turns up
    # (a mapping gap, a backwards-digitised segment, or a hierarki-
    # matching quirk pulling in an unrelated fragment), pick whichever
    # drains the most total upstream river length -- the real main
    # outlet, not a stray dead end.
    sinks = [n for n in Dc.nodes if Dc.out_degree(n) == 0]
    if not sinks:
        raise SystemExit(
            "Could not find an outlet node -- every node has an outgoing edge, which usually "
            "means the network is digitised backwards here. Try REVERSE_FLOW_DIRECTION = True."
        )
    if len(sinks) == 1:
        mouth = sinks[0]
    else:
        Dc_rev = Dc.reverse(copy=False)
        upstream_length = {
            s: sum(Dc_rev.edges[e]["length"] for e in nx.dfs_edges(Dc_rev, s)) for s in sinks
        }
        mouth = max(upstream_length, key=upstream_length.get)
        print(
            f"  WARNING: {len(sinks)} outlet candidate(s) found within this vassdrag (a mapping "
            f"gap, backwards-digitised segment, or hierarki-matching quirk, most likely) -- using "
            f"the one draining the most river length ({upstream_length[mouth]/1000:.1f} km)."
        )

    # Longest path FROM the real mouth to whichever node ends up
    # farthest from it (by total river length) -- "mouth to furthest
    # headwater", always one real downstream<->upstream line.
    dist = nx.single_source_dijkstra_path_length(Gc, mouth, weight="length")
    source = max(dist, key=dist.get)
    node_path = nx.dijkstra_path(Gc, mouth, source, weight="length")

    print(f"  main stem: {len(node_path) - 1} segments, {dist[source]/1000:.1f} km (mouth -> furthest headwater)")

    # Stitch the segment geometries together in path order, starting at
    # the mouth.
    pieces = []
    for a, b in zip(node_path[:-1], node_path[1:]):
        edge = Gc[a][b]
        coords = list(edge["geometry"].coords)
        if node_key(coords[0]) != a:
            coords = coords[::-1]
        pieces.append(LineString(coords))
    merged = linemerge(pieces) if len(pieces) > 1 else pieces[0]
    if merged.geom_type != "LineString":
        raise SystemExit(
            "Could not merge the main stem into one continuous line (linemerge returned "
            f"a {merged.geom_type}) -- the path likely isn't a simple chain. This needs a "
            "look at the actual geometry rather than guessing further."
        )
    return merged


def make_raster_elevation_lookup(dtm_path):
    import rasterio

    src = rasterio.open(dtm_path)
    bounds = src.bounds

    def elevation_at(point):
        if not (bounds.left <= point.x <= bounds.right and bounds.bottom <= point.y <= bounds.top):
            return None
        return next(src.sample([(point.x, point.y)]))[0]

    return elevation_at, src.close


def make_api_elevation_lookup(work_crs, cache_path):
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
                API_URL, params={"nord": lat, "ost": lon, "koordsys": 4326, "geojson": "false"}, timeout=10
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
        time.sleep(0.2)
        return z

    return elevation_at, save_cache


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--river", default=str(ROOT / "data" / "raw" / "nve_elvenett" / "Elv_Elvenett.shp")
    )
    parser.add_argument("--vassdrag", default="Arendalsvassdraget")
    parser.add_argument("--dtm", help="Path to a DTM GeoTIFF (most precise -- see module docstring)")
    parser.add_argument("--hoyde-api", action="store_true", help="Use Kartverket's live point-elevation API instead")
    parser.add_argument("--sample-interval-m", type=float, default=SAMPLE_INTERVAL_M)
    parser.add_argument("--out", default=None, help="Output PNG path (default: output/hoydeprofil_<vassdrag>.png)")
    args = parser.parse_args()

    if not args.dtm and not args.hoyde_api:
        print("Need elevation data: pass --dtm path/to/dtm.tif or --hoyde-api")
        raise SystemExit(1)

    river_path = Path(args.river)
    if not river_path.exists():
        print(f"Could not find river network at {river_path}")
        raise SystemExit(1)

    print(f"Reading river network from {river_path} ...")
    rivers = gpd.read_file(river_path)
    if rivers.crs is None:
        rivers = rivers.set_crs(WORK_CRS)
    rivers = rivers.to_crs(WORK_CRS)

    print(f"Finding the main stem of '{args.vassdrag}' ...")
    main_stem = find_main_stem(rivers, args.vassdrag)

    if args.dtm:
        print(f"Using DTM raster {args.dtm} for elevation ...")
        elevation_at, cleanup = make_raster_elevation_lookup(args.dtm)
    else:
        print("Using Kartverket's live elevation API (this can take a while) ...")
        elevation_at, cleanup = make_api_elevation_lookup(WORK_CRS, HOYDE_CACHE_FILE)

    total_length = main_stem.length
    n_samples = max(2, int(total_length // args.sample_interval_m) + 1)
    distances = [i * total_length / (n_samples - 1) for i in range(n_samples)]
    points = [main_stem.interpolate(d) for d in distances]

    print(f"Sampling elevation at {n_samples} points along {total_length/1000:.1f} km ...")
    elevations = [elevation_at(p) for p in points]
    cleanup()

    missing = sum(1 for z in elevations if z is None)
    if missing:
        print(f"  WARNING: {missing} of {n_samples} points had no elevation data (outside DTM coverage, or the API had no data there) -- these are skipped.")
    kept = [(d, z) for d, z in zip(distances, elevations) if z is not None]
    if len(kept) < 2:
        print("Not enough elevation points came back to build a profile.")
        raise SystemExit(1)
    distances, elevations = zip(*kept)
    distances, elevations = list(distances), list(elevations)

    # find_main_stem() already guarantees distances run mouth -> furthest
    # headwater (see its docstring comment on why that has to be done by
    # anchoring at the real, flow-direction-identified outlet, not by
    # picking whichever orientation happens to look right afterwards).
    # A real river can have local elevation dips (a lake, a meander) but
    # its overall endpoints should still climb outlet -> source; if they
    # don't, silently flipping the x-axis would only hide a genuine
    # problem (REVERSE_FLOW_DIRECTION likely needs toggling here) behind
    # a profile that merely *looks* plausible.
    if elevations[0] > elevations[-1]:
        print(
            f"  WARNING: the outlet end ({elevations[0]:.0f} moh) is HIGHER than the far end "
            f"({elevations[-1]:.0f} moh) -- that shouldn't happen for a real mouth-to-headwater "
            f"line. Check REVERSE_FLOW_DIRECTION at the top of this script; the profile below is "
            f"plotted as-found, not flipped, so this is visible rather than hidden."
        )

    # Same smoothed-gradient method as step 4, applied along the
    # continuous point series instead of per-segment.
    half_window = NATURAL_GRADIENT_WINDOW_M / 2
    candidates = []  # (distance_km, elevation, tier)
    for i, d in enumerate(distances):
        lo = d - half_window
        hi = d + half_window
        if lo < distances[0] or hi > distances[-1]:
            continue
        z_lo = _interp(distances, elevations, lo)
        z_hi = _interp(distances, elevations, hi)
        grad = (z_hi - z_lo) / (hi - lo)  # negative = downhill going downstream (our x increases upstream... )
        # x increases from outlet to source, so going upstream (increasing x) should climb:
        # a real drop shows up as a POSITIVE rise per metre of upstream travel.
        if grad >= NATURAL_GRADIENT_CERTAIN:
            candidates.append((d / 1000, elevations[i], "sikker"))
        elif grad >= NATURAL_GRADIENT_CAUTIOUS:
            candidates.append((d / 1000, elevations[i], "mulig"))

    out_path = Path(args.out) if args.out else ROOT / "output" / f"hoydeprofil_{args.vassdrag.lower()}.png"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    x_km = [d / 1000 for d in distances]
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(x_km, elevations, color="#2b6cb0", linewidth=1.5, label="Elveprofil")
    ax.fill_between(x_km, elevations, min(elevations), color="#2b6cb0", alpha=0.08)

    sikker = [(d, z) for d, z, t in candidates if t == "sikker"]
    mulig = [(d, z) for d, z, t in candidates if t == "mulig"]
    if sikker:
        ax.scatter(*zip(*sikker), marker="^", s=90, color="#6b46c1", edgecolor="white",
                   linewidth=0.8, zorder=5, label=f"Sannsynlig foss (>= {NATURAL_GRADIENT_CERTAIN:.0%})")
    if mulig:
        ax.scatter(*zip(*mulig), marker="^", s=70, facecolor="none", edgecolor="#6b46c1",
                   linewidth=1.3, zorder=5, label=f"Mulig foss ({NATURAL_GRADIENT_CAUTIOUS:.0%}-{NATURAL_GRADIENT_CERTAIN:.0%})")

    ax.set_xlabel("Avstand fra utløp (km)")
    ax.set_ylabel("Høyde (moh)")
    ax.set_title(f"Høydeprofil: {args.vassdrag} (hovedløp, {x_km[-1]:.1f} km)")
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    print(f"Saved {out_path}")

    print(f"\n{len(sikker)} sannsynlig(e) foss, {len(mulig)} mulig(e) foss:")
    for d, z, tier in sorted(candidates):
        label = "SIKKER" if tier == "sikker" else "mulig "
        print(f"  km {d:5.2f}  {z:6.1f} moh  [{label}]")


def _interp(xs, ys, x):
    """Linear interpolation; xs assumed sorted ascending."""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for i in range(1, len(xs)):
        if xs[i] >= x:
            x0, x1 = xs[i - 1], xs[i]
            y0, y1 = ys[i - 1], ys[i]
            t = (x - x0) / (x1 - x0) if x1 > x0 else 0
            return y0 + t * (y1 - y0)
    return ys[-1]


if __name__ == "__main__":
    main()
