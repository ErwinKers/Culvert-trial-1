# Agder kulvert- og vandringshinderkart

An interactive map of culverts/pipes ("kulverter"/"stikkrenner") under
roads in Agder, Norway, coloured by how much of a barrier they are to
migrating fish (salmon, sea trout), combined with terrain/height
information so you can see the landscape (and tell uphill from
downhill) around each site.

Built from the "Aggregert data" sheet of the culvert survey spreadsheet,
plus free public map/terrain data.

## What you get

An HTML file (`output/agder_kulvert_kart.html`) you can open directly
in a web browser (double-click it) -- no server, no login, nothing to
install to just *view* it. It shows:

- One dot per culvert, coloured by migration-barrier severity:
  | Colour | Category | Meaning |
  |---|---|---|
  | 🔴 red | Absolutt | Total barrier -- fish cannot pass |
  | 🟠 orange | Partiell | Partial barrier -- passable under some conditions/for some fish |
  | 🟣 purple | Nedstrøms hinder | Barrier only in the downstream direction |
  | 🟢 green | Ikke hinder | Not a barrier, fish pass freely |
  | 🔵 blue | Neppe fiskeførende | Stream probably doesn't hold fish anyway |
  | ⚪ gray | Ikke angitt | Not assessed / missing data |
- A switchable background map, including a terrain/relief layer
  (OpenTopoMap) that shows contour lines and hillshading, so you can
  see slopes and valleys, plus streams and rivers.
- A line from each culvert's downstream point to its upstream point,
  and (optionally) the elevation difference between the two, since a
  culvert with a big drop in height behaves like a small waterfall for
  fish trying to swim up through it.
- Click any dot for details: place name, municipality, river/stream
  ("vassdrag"), the biologists' comments, diameter, length, etc.

## How it works -- the pipeline

The project is split into small, separate scripts that each do one
thing, so it's easier to follow (and re-run just the part you need):

```
scripts/
  00_eksporter_fra_excel.py   (optional) refresh data/raw/*.csv from a new Excel file
  01_rens_kulvertdata.py      clean coordinates + classify barriers
  02_hent_hoydedata.py        (optional, needs internet) fetch elevation per point
  03_lag_kart.py              build the final interactive map (output/agder_kulvert_kart.html)
```

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

Reads whichever processed file exists (with or without elevation) and
writes `output/agder_kulvert_kart.html`. Open that file in your browser.

## Setup

```bash
pip install -r requirements.txt
python scripts/01_rens_kulvertdata.py
python scripts/02_hent_hoydedata.py   # optional, needs internet, can take a while
python scripts/03_lag_kart.py
```

A ready-made map (built without the optional elevation step) is
already included at `output/agder_kulvert_kart.html`, so you can open
it right away and re-run the pipeline later if you want to add height
data or new source data.

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

## Project layout

```
data/raw/            source data, exported from Excel (small, no photos)
data/processed/      cleaned CSV/GeoJSON + elevation cache (generated by scripts)
scripts/             the four pipeline steps, run in order
output/              the final map (agder_kulvert_kart.html)
```
