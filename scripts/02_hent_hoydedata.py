"""
Step 2 (optional, needs internet): fetch elevation ("height above sea
level") for the downstream and upstream point of every culvert, and work
out the height difference between them.

Why this matters for fish migration
------------------------------------
A culvert that has a big drop in height between its downstream and
upstream end usually behaves like a small waterfall: fish have to jump
up into the pipe, which many cannot do. So the height difference between
the two points is a useful extra clue about how serious a barrier is --
on top of the biologists' own field assessment that we already used in
step 1.

How it works
------------
Kartverket (the Norwegian Mapping Authority) publishes a free web service
that returns the ground elevation for any coordinate in Norway, based on
their national terrain model (a very detailed height map built from
laser/LIDAR scanning). We call that service once per point:

    https://ws.geonorge.no/hoydedata/v1/punkt

We send the point's latitude/longitude, and it answers with the height in
meters. We do this for both the downstream and upstream point of every
culvert, then subtract to get the height difference.

This script needs an internet connection to Kartverket's servers. It is
a separate, optional step (not required for a basic map) because:
  * it can take several minutes to run (one small web request per point,
    with a short pause between requests so we don't overload their free
    service), and
  * elevation is a "nice to have" extra layer -- the map still works
    fine without it.

Re-running the script is fast: results are cached in
data/processed/hoyde_cache.json, so points we already looked up are not
requested again.
"""

import json
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
IN_CSV = ROOT / "data" / "processed" / "kulvert_punkter.csv"
OUT_CSV = ROOT / "data" / "processed" / "kulvert_punkter_med_hoyde.csv"
CACHE_FILE = ROOT / "data" / "processed" / "hoyde_cache.json"

API_URL = "https://ws.geonorge.no/hoydedata/v1/punkt"
PAUSE_BETWEEN_CALLS_SECONDS = 0.2


def load_cache():
    if CACHE_FILE.exists():
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(cache):
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f)


def cache_key(lat, lon):
    # Round to ~1 cm precision, plenty for this purpose, so we don't
    # store a near-infinite number of almost-identical keys.
    return f"{round(float(lat), 6)},{round(float(lon), 6)}"


def fetch_height(session, lat, lon):
    """Ask Kartverket for the ground elevation (meters) at lat/lon.

    Returns None if the point is outside Norway, the service is
    unreachable, or the response doesn't look as expected -- we never
    want one bad point to crash the whole run.
    """
    params = {"nord": lat, "ost": lon, "koordsys": 4326, "geojson": "false"}
    try:
        r = session.get(API_URL, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        punkter = data.get("punkter") or []
        if not punkter:
            return None
        return punkter[0].get("z")
    except Exception as exc:  # noqa: BLE001 - we deliberately want to keep going
        print(f"    Could not fetch height for ({lat}, {lon}): {exc}")
        return None


def main():
    print(f"Reading {IN_CSV} ...")
    df = pd.read_csv(IN_CSV)

    cache = load_cache()
    print(f"Loaded {len(cache)} previously fetched points from cache")

    session = requests.Session()

    def get_or_fetch(lat, lon):
        if pd.isna(lat) or pd.isna(lon):
            return None
        key = cache_key(lat, lon)
        if key in cache:
            return cache[key]
        z = fetch_height(session, lat, lon)
        cache[key] = z
        return z

    elevations_ned = []
    elevations_opp = []
    total = len(df)
    for i, row in df.iterrows():
        z_ned = get_or_fetch(row["lat_ned"], row["lon_ned"])
        z_opp = get_or_fetch(row.get("lat_opp"), row.get("lon_opp"))
        elevations_ned.append(z_ned)
        elevations_opp.append(z_opp)

        # Only pause when we actually made a new network call just now;
        # a cheap way to approximate that is to just always pause a
        # little, it only matters for the (slow) first run anyway.
        time.sleep(PAUSE_BETWEEN_CALLS_SECONDS)

        if (i + 1) % 50 == 0 or (i + 1) == total:
            print(f"  {i + 1}/{total} points processed")
            save_cache(cache)  # save progress so we can resume if interrupted

    save_cache(cache)

    df["elevation_ned_m"] = elevations_ned
    df["elevation_opp_m"] = elevations_opp
    df["elevation_diff_m"] = df["elevation_opp_m"] - df["elevation_ned_m"]

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False)

    n_ok = df["elevation_diff_m"].notna().sum()
    print(f"\nGot a height difference for {n_ok} of {total} culverts")
    print(f"Saved {OUT_CSV}")


if __name__ == "__main__":
    main()
