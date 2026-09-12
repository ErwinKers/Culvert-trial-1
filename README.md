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
  upstream habitat -- river length AND lake area -- would open up if
  that one were fixed, relative to the other barriers on the map --
  bigger dot = bigger win). Each dot is snapped onto the nearest mapped
  stream, instead of the raw (slightly imprecise) field coordinate.
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
- *(If you ran step 4 with `--dtm`)* a small triangle icon at every
  spot the river's slope suggests a **natural** barrier (a waterfall or
  rapid too steep for fish regardless of any culvert) -- solid purple
  for a confident flag, pale/outline purple for "worth checking in the
  field, not certain". A confident natural barrier also stops the
  upstream-habitat colouring, same as another culvert would.
- *(If you ran step 5)* **lakes**, as NVE's own real lake polygons --
  an actual *area*, not just a line, and real measured data (not
  estimated). Lakes count for a lot in the priority score too: a lake
  holds far more fish than the same length of stream, see step 4.
- Click any dot for details: place name, municipality, river/stream
  ("vassdrag"), the biologists' comments, diameter, length, priority
  score, and how many km of river / km2 of lake would open up if that
  culvert were fixed.

## How it works -- the pipeline

The project is split into small, separate scripts that each do one
thing, so it's easier to follow (and re-run just the part you need):

```
scripts/
  00_eksporter_fra_excel.py     (optional) refresh data/raw/*.csv from a new Excel file
  01_rens_kulvertdata.py        clean coordinates + classify barriers
  02_hent_hoydedata.py          (optional, needs internet) fetch elevation per point
  03_lag_kart.py                build the final interactive map (output/agder_kulvert_kart.html)
  04_koble_til_elvenett.py      (optional, needs NVE river data) snap to river + trace upstream + score
  05_legg_til_innsjoer.py       (optional, needs NVE lake data) add the lake layer
  06_legg_til_feltdata.py       (optional) bring in two more sheets from the original Excel file
  07_lag_rapport.py             (optional) write a prioritisation report (Word doc) with a draft søknad form
```

Run them in order (0, 2, 4, 5, 6, 7 are optional -- 1 then 3 alone
already gives you a working map, just without the river network).

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
python scripts/04_koble_til_elvenett.py --river data/raw/nve_elvenett/Elv_Elvenett.shp --kommune Arendal --innsjo data/raw/nve_innsjo/Innsjo_Innsjo.shp
```

This is what makes "how much space opens up upstream" possible, and
where the priority score is worked out. It:

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
     rapid** -- a stretch steep enough that most anadromous fish
     couldn't climb it regardless of any culvert.

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
5. Turns each culvert's (correctly-stopped) upstream length -- and, if
   you pass `--innsjo`, the surface area of any lakes along that
   reachable stretch -- into a **0-100 priority score**. Rather than
   inventing a "km of river is worth this many km2 of lake" exchange
   rate, each culvert is ranked (0-1) on river length and separately on
   lake area among the other barriers in this run, and the two ranks
   are blended 50/50 (`LAKE_SCORE_WEIGHT` near the top of the script) --
   100 = ranks at or near the top on the combined measure, 0 = the
   least. This is what step 3 uses to size each dot on the map.
   Without `--innsjo`, the score falls back to river length alone.

Only "Absolutt" and "Partiell" culverts count as barriers here, since
those are the only ones with an upstream stretch worth marking.

**Detecting natural barriers (optional, needs elevation data) -- two
ways to get it:**

- `--hoyde-api` -- **no file to download.** Uses Kartverket's free
  point-elevation web service (the same one step 2 already uses) to
  look up elevation directly, over the internet, at just the ~2 points
  per river segment this method actually needs (roughly 1,800 requests
  for Arendal's 883 segments -- the same order of magnitude as step
  2's per-culvert lookups, not the thousands you'd need for a dense
  scan). Cached to `data/processed/hoyde_cache_elvenett.json`, so a
  re-run only fetches what's missing. This is the easiest option if
  you just want to try the feature.
- `--dtm path/to/dtm.tif` -- a local "digital terrain model" GeoTIFF
  you already have (e.g. from Kartverket's <https://hoydedata.no/>
  download service, the same site style as the NVE map data export).
  Works fully offline once you have the file; worth it if you're doing
  this for many kommuner and don't want to make thousands of
  individual web requests.

Either way, both flag *and* stop at natural barriers, not just other
culverts.

The method is a **gradient smoothed over ~100 m of river**, not just
one segment's own (sometimes short and noisy) slope: for every stretch
of river, we look at the average slope across roughly 50 m upstream
and 50 m downstream of it (walking into neighbouring segments as
needed to gather that much length), and classify it:

| Smoothed gradient | Meaning | Effect |
|---|---|---|
| >= 10% (`NATURAL_GRADIENT_CERTAIN`) | Likely a natural barrier | Stops the upstream walk, same as an Absolutt culvert |
| 7-10% (`NATURAL_GRADIENT_CAUTIOUS`) | Possible natural barrier, uncertain | Flagged on the map (pale triangle icon) but does *not* stop the walk -- a gradient alone in this range isn't reliable enough to automatically discard habitat |
| < 7% | Not flagged | -- |

Both thresholds and the 100 m window size are constants near the top
of the script if you want to tune them.

Without either flag, natural-barrier detection is simply skipped and
only Absolutt culverts stop the walk -- everything else still works.

*(The gradient classification itself was validated against small
hand-built test rasters with known slopes in them -- 12%, 8%, and 3%
steps, correctly sorted into "certain"/"cautious"/"not flagged". The
`--hoyde-api` plumbing (coordinate conversion, caching, the live HTTP
call) was validated by mocking the API response end-to-end -- correct
coordinates were sent and the results flowed through correctly -- but
neither path has been run against real elevation data for Arendal yet,
since this sandbox can't reach Kartverket's service and we don't have
a downloaded DTM file either.)*

**Where to get the river data:** an NVE map data export
(`nedlasting.nve.no`) for the kommune you want to cover. The `.zip`
contains several folders under `NVEData/`; this project uses:

| Folder in the export | Goes to | Used by |
|---|---|---|
| `Elv/Elv_Elvenett.*` | `data/raw/nve_elvenett/` | step 4 (network + barriers) |
| `Innsjo/Innsjo_Innsjo.*` | `data/raw/nve_innsjo/` | step 4 (lake area for scoring) + step 5 (lake map layer) |

(Each is 4-5 files -- `.shp`/`.shx`/`.dbf`/`.prj`/optionally `.cpg` --
that belong together; unzip all of them, not just the `.shp`.) This
project currently ships with an Arendal-kommune export already
validated end-to-end against the real data (883 real stream segments,
correct branching, sensible upstream lengths, 201 real lakes, 620 river
segments confirmed running through a lake). For another kommune, get a
matching export and update `KOMMUNE_FILTER` (`scripts/03_lag_kart.py`)
and `--kommune` to match.

**One thing worth a second look:** NVE digitizes Elvenett lines from
upstream to downstream, and this script relies on that. The Arendal
result looks topologically correct (proper branching streams, sensible
lengths), but if a river you know well looks reversed on the map
(orange/red appearing *downstream* of a barrier instead of upstream),
set `REVERSE_FLOW_DIRECTION = True` near the top of the script and
re-run. Also check the console output for how many culverts snapped
more than `SUSPICIOUS_SNAP_DISTANCE_M` (50 m) from any mapped stream
(13 of 44 in the current Arendal run) -- those are worth a manual look
(either a coordinate error, or the culvert is on a stream too small for
Elvenett to include). **Step 3 draws these on the map too:** a dashed
line from the original field coordinate to the point actually used,
with a small white/black dot marking the original -- so a coordinate
that lands in the middle of a lake, or nowhere near any mapped stream,
is immediately visible instead of silently trusted. Only shown beyond
50 m (`SNAP_WARNING_DISTANCE_M` in `scripts/03_lag_kart.py`) since a
few metres of GPS noise is normal and not worth flagging.

### Step 5 -- (optional) add the lake layer to the map

```bash
python scripts/05_legg_til_innsjoer.py --innsjo data/raw/nve_innsjo/Innsjo_Innsjo.shp
```

Copies NVE's real lake polygons (reprojected to plain longitude/
latitude) to `data/processed/innsjoer.geojson` for step 3 to draw as an
actual area layer. This is a display-only step -- the *scoring* use of
lake area (factoring it into each culvert's priority score) happens in
step 4 via `--innsjo`, since that's where the scoring lives; run step 4
with `--innsjo` first if you want lake-aware scores, then this step to
also see the lakes on the map.

**We looked for lake depth too, and it isn't in this data.** The plan
was to combine depth and surface area into a volume-based "how much
living space for fish" estimate, as requested -- but NVE's `Innsjo`
export carries a `dybdekart` field for exactly this ("is there a depth
survey for this lake"), and for all 201 lakes in the Arendal export
it's empty: no bathymetry is on file for any of them here. Rather than
invent a depth-from-surface-area formula -- which would have the same
unfounded-precision problem as the river discharge/width estimate this
project tried and then dropped (see the note below) -- the priority
score currently uses lake **surface area** only, which is real,
measured NVE data. If you can get real depth figures for any of these
lakes (NVE's separate bathymetry surveys, where they exist, or a local
source), that would be the right number to fold in.

*(An earlier version of this project also estimated river discharge,
width, and flow speed, shown as a coloured "ribbon" layer. It's been
removed: discharge was assigned per REGINE catchment unit, and since
one unit typically covers a main-stem reach and its tributaries
together, a small side-stream right next to a big river was shown with
the same discharge/colour as the main river -- misleading rather than
useful. Nothing currently replaces it; if you want a river-as-area
visualisation, factor in a `vassdragNr`-based split between
main-stem and tributary segments before estimating a per-segment
discharge, unlike the flat per-unit assignment this project used.)*

### Step 6 -- (optional) bring in two more sheets from the Excel file

```bash
python scripts/06_legg_til_feltdata.py --kommune Arendal
```

The original workbook has 20 sheets; this project had only ever used
"Aggregert data". Two more turned out to have real, field-collected
data worth adding:

- **"Prioritering av stikkrenner"** ("prioritisation of culverts") --
  the biologists' own field assessment for a subset of culverts:
  whether it's actually on an anadromous-fish reach ("Anadrom
  strekning?"), their own priority ranking, what kind of fix it needs
  (light cleanup / minor improvement / extensive rebuild / "unclear,
  needs a site visit"), and a free-text expert comment. This sheet uses
  a different coordinate system than "Aggregert data" (EPSG:25833
  instead of EPSG:25832) -- both real, just exported differently -- so
  matching rows to our existing culverts is done by coordinate,
  accepting only matches within `MATCH_DISTANCE_M` (15 m). All 44
  Arendal barrier culverts matched, at essentially 0 m (i.e. the exact
  same recorded site), and 9 of them are confirmed anadromous-fish
  reaches.

  **This already caught something real:** the culvert this project's
  own scoring ranks #1 (`id 536`, Langsæveien) has an expert comment
  saying it's *"antakelig ikke noe poeng å renske opp her da det ikke
  er sjøørret her, og det er gjedde i Langsævannet"* -- "probably not
  worth clearing since there's no sea trout here, and there's pike in
  the lake above." The scoring model only measures reachable habitat
  *area*; it has no way to know a species isn't present there, or that
  a predatory fish already occupies the lake. This field is now in the
  popup (open the map and click that dot), but **not yet factored into
  the priority score itself** -- only 9 of 44 culverts have a definite
  "Ja"/"Nei" here, so a blank isn't evidence of absence, and how to
  treat "Nei" (zero out the score entirely? just flag it for manual
  review?) is a judgement call worth making deliberately rather than
  guessing.

- **"SØ naturlig hunder"** ("suspected natural barriers") -- an actual
  field register of observed/suspected natural barriers, several
  cross-referenced against Norway's official salmon register
  ("Lakseregistret"). This is real, ground-truthed data -- better than
  the gradient *estimate* in step 4 wherever it exists. 6 of the
  register's 518 entries (across all of Agder) fall within Arendal;
  both layers stay on the map, clearly distinguished (a black diamond
  for the field register vs. purple triangles for the modelled
  estimate), since the field register only covers places someone
  has actually been to check.

### Step 7 -- (optional) write a prioritisation report

```bash
python scripts/07_lag_rapport.py --kommune Arendal --antall 5
```

Writes `output/prioriteringsrapport.docx` (a Word document): a short
plain-language report for the top N barriers (5 by default, `--antall`
to change it), meant to be handed to someone who won't open the
interactive map. For each of the top culverts it lists where it is, how
much river/lake would open up if fixed (same figures as the map popup,
rounded to 2 decimals throughout), the field comments, and a
**suggested action** -- e.g. "clear debris", "replace an undersized
pipe", "build a gentle ramp/threshold so fish don't have to jump".
That suggestion is picked in order of how reliable the source is:

1. The biologists' own `type_tiltak` field from step 6 ("Lett rensk",
   "Mindre utbedring", "Omfattende utbedring", ...), when present --
   this is a professional's own classification, so it's used as-is.
2. Otherwise, a small set of Norwegian keyword rules over the free-text
   comment fields (e.g. "hopp"/"for bratt" -> suggest a gentler
   slope/threshold; "gitter"/"rist" -> check the grate; "kvist"/"slam"
   -> clear debris). This is a heuristic, not a field assessment, and
   the report says so next to each suggestion.
3. If neither matches anything, the report says a site visit is needed
   rather than guessing.

**It also drafts a filled-in application form** ("Søknad om tillatelse
til fysiske tiltak i vassdrag") as an appendix, for the single #1
ranked culvert, based on the paper form Statsforvalteren uses. It
mirrors every section of that form and fills in only what the
project's own data actually supports (kommune, vassdrag, a
problem/action description built from the data above) -- every field
requiring information this project doesn't have (applicant details,
property/landowner info, legal considerations) is left as an explicit
`[FYLLES INN AV SØKER]` placeholder rather than invented. **The source
form lists "Fylkesmannen i Rogaland" as the recipient** -- both an
outdated name (renamed Statsforvalteren in 2021) and the wrong county
(Rogaland, not Agder) for this project -- so the draft flags this in
bold rather than guessing a submission address; check the current
address with Statsforvalteren i Agder before sending anything.

This report is a drafting aid, not a substitute for the biologists'
judgement or a ready-to-submit application -- read it over, and
especially check the placeholder fields and the address, before using
it for anything official.

## Setup

```bash
pip install -r requirements.txt
python scripts/01_rens_kulvertdata.py
python scripts/02_hent_hoydedata.py       # optional, needs internet, can take a while
python scripts/04_koble_til_elvenett.py --river data/raw/nve_elvenett/Elv_Elvenett.shp --kommune Arendal --innsjo data/raw/nve_innsjo/Innsjo_Innsjo.shp
python scripts/05_legg_til_innsjoer.py    # optional, lake map layer
python scripts/06_legg_til_feltdata.py --kommune Arendal   # optional, real field-assessment data
python scripts/03_lag_kart.py
python scripts/07_lag_rapport.py --kommune Arendal --antall 5   # optional, Word report + draft søknad
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
- **Natural-barrier detection needs elevation data** (`--dtm` or
  `--hoyde-api`) -- without either, only other Absolutt culverts stop
  the upstream walk, so a stretch of river blocked by a natural
  waterfall higher up (with no culvert involved) would still show as
  "opened up". This is also why the shipped map has no natural-barrier
  icons on it at all: neither flag was passed when it was built, since
  this sandbox can't reach Kartverket's API and there's no downloaded
  DTM file in the project either -- the check was skipped, not run and
  found nothing. Pass `--hoyde-api` yourself (needs internet, no
  download) to actually see this layer.
- **Lake area in the score uses surface area only, not depth** -- NVE's
  export has no bathymetry on file for any of the 201 Arendal lakes
  (see step 5). A wide, shallow pond and a deep lake of the same
  surface area currently score the same.
- **Priority scores are relative, not absolute.** The 0-100 score is
  ranked against the *other barriers processed in the same run* -- if
  you change the kommune filter or the input data, the same culvert can
  get a different score. It's meant for comparing barriers to each
  other within one map, not as a fixed, portable number.
- **Only covers Arendal right now.** The river/lake data and the
  `KOMMUNE_FILTER`/`--kommune` settings are scoped to Arendal. The
  pipeline works the same way for any other kommune once you have a
  matching NVE export for it.
- **"Anadrom strekning?" isn't factored into the score yet**, even
  though step 6 pulls it in and puts it in the popup -- see the
  Langsæveien example in step 6. Worth deciding deliberately how to use
  it (exclude "Nei" entirely? just deprioritise it?) rather than
  guessing.
- **A promising option not yet built: Vann-Nett.** The Excel workbook's
  "VF i Vannnett" sheet (2,580 rows, all of Agder) is an export from
  Norway's official water body register, with an authoritative
  "Anadrom fisk" (Ja/Nei) field per water body -- a stronger source
  than "Anadrom strekning?" for the same question, and covering every
  water body, not just the ones a student happened to note it for.
  Wiring it in needs a join between this project's culverts/REGINE
  codes and Vann-Nett's own `VannforekomstID` scheme, which don't share
  a common key directly -- worth doing, just not done here yet.

## Project layout

```
data/raw/                   source data, exported from Excel (small, no photos)
data/raw/nve_elvenett/      NVE Elvenett river network shapefile for the current kommune (step 4)
data/raw/nve_innsjo/        NVE lake polygons (step 4 scoring + step 5 map layer)
data/processed/             cleaned CSV/GeoJSON + coloured river network + lakes + field data (generated by scripts)
scripts/                    the seven pipeline steps, run in order
output/                     the final map (agder_kulvert_kart.html) + the prioritisation report (prioriteringsrapport.docx)
```

## Wishlist for better source data

If you're asking a GIS colleague for anything, these are the gaps this
project actually ran into (in rough order of impact):

- **A real elevation raster (DTM) for Arendal**, or confirmation that
  Kartverket's høydedata service has good coverage here -- this project
  currently has to fetch elevation one point at a time over the
  internet (`--hoyde-api`) instead of using a proper terrain model, and
  neither path has actually been run against real data yet in this
  environment (see step 4). A downloaded DTM `.tif` would make natural
  (waterfall/rapid) barrier detection both faster and offline-capable.
- **Vann-Nett water body polygons with the "Anadrom fisk" attribute**
  for Arendal's streams/lakes -- this is the authoritative national
  register for where anadromous fish are actually present, and would
  replace the much sparser "Anadrom strekning?" field this project has
  today (only 9 of 44 barrier culverts have a definite answer; see step
  6). It would let the priority score account for fish presence, not
  just reachable habitat area.
- **Corrected coordinates for the 13 culverts that snapped >50 m from
  any mapped stream** (Step 4's console output lists them, and they're
  shown as dashed lines on the map) -- either the field GPS point is
  off, or the stream they're on is smaller than what Elvenett maps.
- **Lake depth/bathymetry data**, if any exists for the 201 lakes in
  the Arendal export -- NVE's own lake layer has no bathymetry on file
  for any of them (see step 5), so the score currently uses surface
  area only, treating a shallow pond the same as a deep lake of equal
  area.
