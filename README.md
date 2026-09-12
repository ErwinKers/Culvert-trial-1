# Agder kulvert- og vandringshinderkart

An interactive map of culverts/pipes ("kulverter"/"stikkrenner") under
roads in Agder, Norway, coloured by how much of a barrier they are to
migrating fish (salmon, sea trout), combined with the real river/stream
network so you can see exactly how much habitat each barrier is cutting
off, and terrain/height information so you can see the landscape (and
tell uphill from downhill) around each site.

Built from the "Aggregert data" sheet of the culvert survey spreadsheet,
plus NVE's official river network data and free public map/terrain data.

**Current scope: Arendal kommune only** (see `KOMMUNE_FILTER` in
`scripts/03_lag_kart.py` and `--kommune` in `scripts/04_koble_til_elvenett.py`)
-- this matches the NVE river network export the project currently has.
To cover a different kommune, get an NVE Elvenett export for that area
(see step 4) and change the kommune filter in both scripts.

## What you get

An HTML file (`output/agder_kulvert_kart.html`) you can open directly
in a web browser (double-click it) -- no server, no login, nothing to
install to just *view* it. The map only shows culverts that are
actually migration barriers -- everything else is left out on purpose.
It shows:

- One dot per barrier culvert, coloured red (Absolutt/total) or orange
  (Partiell/partial), **sized by its priority score** (0-100: how much
  upstream habitat would open up if that one were fixed, relative to
  the other barriers on the map -- bigger dot = bigger win). Each dot
  is snapped onto the nearest mapped stream, instead of the raw
  (slightly imprecise) field coordinate.
- *(If you ran step 4)* the WHOLE river/stream network from NVE's real
  Elvenett data (not just a picture -- actual line-by-line geometry),
  coloured:
  | Colour | Meaning |
  |---|---|
  | 🔴 red | Upstream of a total barrier (and not blocked by anything else before reaching it) |
  | 🟠 orange | Upstream of a partial barrier (same condition) |
  | 🔵 blue | Not affected -- either nowhere near a barrier, or downstream of one (a barrier only blocks upward passage), or upstream of a point fish can't reach anyway |

  The colouring stops exactly at the point of another blocking barrier
  further upstream (another Absolutt culvert, or -- if you supply
  elevation data -- a natural waterfall/rapid too steep to climb), so a
  stretch of river only counts as "opened up" if fixing that one
  culvert would genuinely make it reachable.
- A switchable background map, including a terrain/relief layer
  (OpenTopoMap, the default) that shows contour lines and hillshading,
  so you can see slopes and valleys.
- Click any dot for details: place name, municipality, river/stream
  ("vassdrag"), the biologists' comments, diameter, length, priority
  score, and how many km of river would open up if that culvert were
  fixed.

## How it works -- the pipeline

The project is split into small, separate scripts that each do one
thing, so it's easier to follow (and re-run just the part you need):

```
scripts/
  00_eksporter_fra_excel.py     (optional) refresh data/raw/*.csv from a new Excel file
  01_rens_kulvertdata.py        clean coordinates + classify barriers
  02_hent_hoydedata.py          (optional, needs internet) fetch elevation per point
  03_lag_kart.py                build the final interactive map (output/agder_kulvert_kart.html)
  04_koble_til_elvenett.py      (optional, needs NVE river data) snap to river + trace upstream
```

Run them in order (0 and 2 and 4 are optional -- 1 then 3 alone already
gives you a working map).

### Step 0 -- (optional) re-export from Excel

`data/raw/aggregert_data_raw.csv` already contains the "Aggregert data"
sheet from the workbook you shared, exported as a small CSV (the full
Excel file is ~9 MB because other sheets have embedded photos -- we
don't need those). If you ever get an updated Excel file, regenerate
the CSV with:

```bash
python scripts/00_eksporter_fra_excel.py path/to/All_kulvertdata_samla_Agder.xlsx
```

### Step 1 -- clean the data

```bash
python scripts/01_rens_kulvertdata.py
```

This is the "translation" step. Two things needed fixing before the
data could go on a map:

1. **Coordinate format.** The spreadsheet writes coordinates the
   Norwegian way, e.g. `423 866,481` (space between thousands, comma
   as decimal point). Regular map libraries expect plain numbers like
   `423866.481`, so we strip the spaces and swap the comma for a dot.
2. **Coordinate system.** The numbers themselves are in **UTM zone 32N
   (EPSG:25832)** -- a flat, metre-based grid that surveyors use, which
   is what this dataset turned out to use (we confirmed this by test
   converting a few points and checking that they land inside Agder).
   Web maps expect **longitude/latitude (EPSG:4326)** instead -- the
   same system your phone's GPS uses. The `pyproj` library does this
   conversion for us.

It also turns the free-text migration-barrier assessment
("Justert konsekvens") into the six fixed categories + colours listed
in the table above, and saves everything to
`data/processed/kulvert_punkter.csv` (and a `.geojson` copy, handy if
you ever want to open this in QGIS or similar GIS software).

Only rows that have a usable downstream coordinate are kept (600 out of
856 rows in the original file -- the rest had no coordinate filled in).

### Step 2 -- (optional) fetch elevation / height data

```bash
python scripts/02_hent_hoydedata.py
```

This calls Kartverket's (the Norwegian Mapping Authority) free
elevation web service once per point, for both the downstream and
upstream point of every culvert, and works out the height difference.
It needs an internet connection, and can take several minutes to run
(there's a small pause between requests so we don't overload the free
service) -- so it's a separate, optional step. Results are cached in
`data/processed/hoyde_cache.json`, so re-running it later is instant
for points already looked up.

**Note:** ground elevation at two points near a culvert is an
approximation of the actual pipe drop, not a survey-grade measurement.
Treat the height-difference numbers as a helpful extra clue, not a
substitute for the biologists' field assessment.

### Step 3 -- build the map

```bash
python scripts/03_lag_kart.py
```

Reads whichever processed file exists (plain, with elevation, or with
the river network from step 4) and writes
`output/agder_kulvert_kart.html`. Open that file in your browser.

### Step 4 -- (optional) snap to the real river network + colour it by impact

```bash
python scripts/04_koble_til_elvenett.py --river data/raw/nve_elvenett/Elv_Elvenett.shp --kommune Arendal
```

This is what makes "how much space opens up upstream" possible. It:

1. Loads NVE's **Elvenett** river network data -- real line-by-line
   geometry for every mapped stream, built as a proper network where
   streams connect exactly at confluences. That's different from the
   OpenTopoMap background picture in step 3, which just *looks like*
   rivers but isn't data we can compute with.
2. **Snaps** each barrier culvert (in the chosen kommune) onto the
   nearest line in that network -- since the field GPS coordinate can
   be a little off, we assume the culvert is really wherever the
   closest mapped stream is.
3. **Walks upstream** through the network graph from that snapped
   point, collecting every segment that genuinely becomes reachable --
   handling branches/tributaries correctly, without double-counting --
   and **stopping the walk on any branch** as soon as it hits:
   - another **Absolutt** (total) barrier further up that branch --
     fixing the lower culvert wouldn't matter if fish still can't get
     past a total blockage above it, or
   - (only if you pass `--dtm`, see below) a **natural waterfall or
     rapid**: a drop of more than 2 m within 5 m of river length, which
     most anadromous fish can't climb regardless of any culvert.

   A **Partiell** (partial) barrier upstream does *not* stop the walk,
   since fish can still get through it at least some of the time. The
   resulting length becomes the `oppstrom_lengde_km` figure in each
   culvert's popup.
4. **Colours the network accordingly**, splitting each mapped river
   segment exactly at every barrier point (so the colour never bleeds
   into the stretch downstream of a barrier just because that happened
   to share the same underlying map line) -- red upstream of a total
   barrier, orange upstream of a partial one, blue everywhere else. The
   result is `data/processed/elvenett_farget.geojson`, which step 3
   draws in full.
5. Turns each culvert's (correctly-stopped) upstream length into a
   **0-100 priority score**, relative to the other barriers processed
   in the same run: 100 = fixing this one would open up the most
   habitat of all of them, 0 = the least. This is what step 3 uses to
   size each dot on the map.

Only "Absolutt" and "Partiell" culverts count as barriers here, since
those are the only ones with an upstream stretch worth marking.

**Detecting natural waterfalls (optional, needs an elevation raster):**
pass `--dtm path/to/dtm.tif` pointing at a local "digital terrain
model" GeoTIFF (e.g. from Kartverket's <https://hoydedata.no/>
download service) to also stop the upstream walk at natural barriers,
not just at other culverts. Without `--dtm`, this step is simply
skipped and only Absolutt culverts stop the walk -- everything else
still works. The 2 m / 5 m rule of thumb is set as
`NATURAL_BARRIER_DROP_M` / `NATURAL_BARRIER_WINDOW_M` near the top of
the script if you want to tune it. (This part of the script was
validated against a small hand-built test raster with a known 3 m step
in it, not against a real DTM -- we don't have one for Arendal yet.)

**Where to get the river data:** an NVE map data export
(`nedlasting.nve.no`) for the kommune you want to cover, as a `.zip`
containing an `Elv` folder with `Elv_Elvenett.shp`/`.shx`/`.dbf`/`.prj`
(all four files belong together). Unzip those four files into
`data/raw/nve_elvenett/` in this project. This project currently ships
with an Arendal-kommune export already validated end-to-end against the
real data (883 real stream segments, correct branching, sensible
upstream lengths) -- the screenshot in this repo's history shows the
result. For another kommune, get a matching export and update
`KOMMUNE_FILTER` (`scripts/03_lag_kart.py`) and `--kommune` to match.

**One thing worth a second look:** NVE digitizes Elvenett lines from
upstream to downstream, and this script relies on that. The Arendal
result looks topologically correct (proper branching streams, sensible
lengths), but if a river you know well looks reversed on the map
(orange/red appearing *downstream* of a barrier instead of upstream),
set `REVERSE_FLOW_DIRECTION = True` near the top of the script and
re-run. Also check the console output for how many culverts snapped
more than 100 m from any mapped stream (12 of 44 in the current Arendal
run) -- those are worth a manual look (either a coordinate error, or
the culvert is on a stream too small for Elvenett to include).

## Setup

```bash
pip install -r requirements.txt
python scripts/01_rens_kulvertdata.py
python scripts/02_hent_hoydedata.py       # optional, needs internet, can take a while
python scripts/04_koble_til_elvenett.py --river data/raw/nve_elvenett/Elv_Elvenett.shp --kommune Arendal
python scripts/03_lag_kart.py
```

A ready-made map (Arendal, with the coloured river network but without
the optional elevation step) is already included at
`output/agder_kulvert_kart.html`, so you can open it right away and
re-run the pipeline later if you want to add height data, cover another
kommune, or refresh the source data.

**You need an internet connection when you *open* the map** (not when
you build it) -- the background map images (terrain, streets,
satellite) are loaded live from OpenTopoMap / OpenStreetMap / Esri each
time you view it.

## Notes and things to check

- **Kartverket's own topographic layer** is included as an extra,
  switched-off-by-default background option, since it's normally the
  most detailed option for Norway specifically. Public tile-service
  addresses occasionally change; if it stays blank when you switch to
  it, look up the current WMTS address at
  <https://kartverket.no/api-og-data/apne-kartdata> and update the URL
  in `scripts/03_lag_kart.py` (`add_base_layers` function) -- every
  other layer keeps working regardless.
- **Duplicate entries.** The original spreadsheet has a `Dublett`
  column flagging some rows as possible duplicates of others (e.g. the
  same culvert recorded by two different surveys). This script does
  **not** remove those automatically, since interpreting that column
  correctly needs domain knowledge this script doesn't have -- you may
  want to review `data/raw/aggregert_data_raw.csv` for that column
  before treating counts as exact.
- **Rows without coordinates** (256 of 856) are simply excluded from
  the map, since there is nowhere to plot them; they still exist in the
  original data.
- **Priority scores are relative, not absolute.** The 0-100 score is
  scaled against the *other barriers processed in the same run* -- if
  you change the kommune filter or the input data, the same culvert can
  get a different score. It's meant for comparing barriers to each
  other within one map, not as a fixed, portable number.
- **Natural-barrier detection needs an elevation raster you supply**
  (`--dtm`) -- without one, only other Absolutt culverts stop the
  upstream walk, so a stretch of river blocked by a natural waterfall
  higher up (with no culvert involved) would still show as "opened up".
- **Only covers Arendal right now.** Both the river data and the
  `KOMMUNE_FILTER`/`--kommune` settings are scoped to Arendal. The
  pipeline works the same way for any other kommune once you have a
  matching NVE Elvenett export for it.

## Project layout

```
data/raw/                 source data, exported from Excel (small, no photos)
data/raw/nve_elvenett/    NVE Elvenett river network shapefile for the current kommune (step 4)
data/processed/           cleaned CSV/GeoJSON + elevation cache + coloured river network (generated by scripts)
scripts/                  the five pipeline steps, run in order
output/                   the final map (agder_kulvert_kart.html)
```
