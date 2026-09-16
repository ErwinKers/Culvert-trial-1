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
  bigger dot = bigger win). The dot is drawn at whichever of
  Elvenett/FKB-Vann is actually closest to the field coordinate (step
  4) -- FKB-Vann when it has a water feature closer than Elvenett's own
  line (more precise: aerial photogrammetry vs. a generalised network
  product), Elvenett's snapped point otherwise. The upstream trace and
  priority score are separately computed from wherever on *Elvenett*
  the walk actually starts (FKB-Vann has no network/flow-direction data
  of its own, so it can only inform *which* Elvenett edge that is, not
  replace it) -- both derived from the same FKB-Vann-informed decision,
  in one place in step 4, so they can't silently drift out of sync with
  each other. On the real Arendal run, FKB-Vann placed 30 of 44 barrier
  culverts' dots; the two distances involved (marker-to-field-point,
  and Elvenett-edge-to-field-point) are both shown in the popup, along
  with which one applies.
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
  culvert would genuinely make it reachable. A culvert whose Elvenett
  edge is more than 50 m from its field coordinate never colours the
  network at all, for the same reason it gets no priority score (see
  the black-ring bullet below) -- it isn't actually a barrier on that
  stream, so it shouldn't get to mark it "blocked" red/orange, or stop
  another culvert's walk from continuing through it either.
- A switchable background map, including a terrain/relief layer
  (OpenTopoMap, the default) that shows contour lines and hillshading,
  so you can see slopes and valleys.
- **The kommune's own administrative boundary**, as a dashed outline
  (fetched once from Kartverket's Kommuneinfo API, see step 3), so you
  can see exactly where the kommune -- and so this map's coverage --
  actually ends, and the map now zooms to fit the whole kommune by
  default instead of just tightly around the culvert points.
- *(If you ran step 4 with `--dtm` or `--hoyde-api`, as the shipped map
  does)* a small triangle icon at every spot the river's slope suggests
  a **natural** barrier (a waterfall or rapid too steep for fish
  regardless of any culvert) -- solid purple for a confident flag,
  pale/outline purple for "worth checking in the field, not certain". A
  confident natural barrier also stops the upstream-habitat colouring,
  same as another culvert would. 33 confident + 30 possible on the real
  Arendal river network.
- *(If you ran step 5)* **lakes**, as NVE's own real lake polygons --
  an actual *area*, not just a line, and real measured data (not
  estimated), shown filled in blue with their own legend entry. Lakes
  count for a lot in the priority score too: a lake holds far more fish
  than the same length of stream, see step 4.
- *(If an FKB-Vann export is present, see step 8)* **FKB-Vann's own
  river/lake polygons**, teal-coloured, as a separate switchable
  overlay next to Elvenett -- FKB-Vann is positionally more precise but
  isn't a network, so the two datasets are shown side by side rather
  than merged, letting you see at a glance where one has a stream the
  other doesn't.
- *(If step 4 traced any -- needs `--dtm`/`--hoyde-api`)* those same
  FKB-Vann polygons **coloured red/orange** on top of the plain teal
  layer, for the handful of culverts Elvenett can't trace at all (see
  the black-ring bullet below) -- direction inferred from elevation
  since FKB-Vann has none of its own. Same colour meaning as the
  Elvenett layer, just coarser (whole ~10-50 m polygons, not an exact
  cut point).
- *(If step 4 found any)* a **black dashed ring** around a culvert
  whose Elvenett edge is more than 50 m from its field coordinate -- not
  genuinely a migration barrier *on* that stream, so it doesn't colour
  it red/orange, doesn't stop any other culvert's upstream walk on it
  either, and its own priority score and upstream-habitat figures are
  **not computed at all** rather than presenting a plausible-looking
  number derived from a distant, unrelated stream. 13 of 44 in the
  current Arendal run (7 of those with FKB-Vann confirming real water
  right at the field point -- definitely a real barrier, just not one
  Elvenett maps there; the other 6 lack even that confirmation, so the
  field coordinate itself might be off) -- see step 4's
  `score_upalitelig` note below. Excluded from step 7's ranked report
  entirely (there's no number to rank by), but still listed there by
  name as real, mapped barriers.
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
  08_sjekk_fkb_vann.py          (optional, needs an FKB-Vann export) cross-check culvert positions against FKB-Vann
  09_hoydeprofil.py             (optional, needs elevation data) height profile of a whole vassdrag, with candidate foss locations
```

Run them in order (0, 2, 4, 5, 6, 7, 8, 9 are optional -- 1 then 3 alone
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

**Kommune boundary outline:** drawn from
`data/raw/kommunegrense/arendal_4203.geojson`, a one-time fetch from
Kartverket's free, no-login Kommuneinfo API --
`https://ws.geonorge.no/kommuneinfo/v1/kommuner/4203/omrade?utkoordsys=4326`
(4203 is Arendal's kommunenummer; look one up by name at
`https://ws.geonorge.no/kommuneinfo/v1/sok?knavn=<name>` for another
kommune). Small (~100 KB) and static -- kommune boundaries essentially
never change -- so it's just committed to the repo rather than fetched
on every run. If it's missing, step 3 still works, just without the
outline layer.

### Step 4 -- (optional) snap to the real river network + colour it by impact

```bash
python scripts/04_koble_til_elvenett.py --river data/raw/nve_elvenett/Elv_Elvenett.shp --kommune Arendal --innsjo data/raw/nve_innsjo/Innsjo_Innsjo.shp --fkb data/raw/fkb_vann/fkb_vann_omrade_arendal.shp
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
   closest mapped stream is. **If an FKB-Vann export is given (`--fkb`,
   on by default, pointing at the file step 8 uses)** and it has a
   water feature closer to the field coordinate than Elvenett's own
   line is, FKB-Vann's own point is used for two things at once, since
   FKB-Vann is positionally more precise (aerial photogrammetry vs. a
   generalised network product):
   - **as the actual marker position** shown on the map and in the
     popup (`lon_snappet`/`lat_snappet`) -- the more accurate of the
     two, so that's what gets drawn;
   - **as the input for deciding which Elvenett edge** (and where along
     it) the upstream walk below starts from, instead of the raw field
     coordinate -- the walk still needs an actual Elvenett graph edge,
     FKB-Vann has no equivalent network/flow-direction data of its own.

   Both uses come from the same FKB-Vann-informed decision, computed
   once, so the walk/coloured trace/score can't silently drift out of
   sync with wherever the marker ends up drawn -- even though the
   marker and the Elvenett edge it traces from can now legitimately be
   a little apart (the same way a raw field coordinate always could be
   a little off the Elvenett line it snapped to -- see
   `SNAP_WARNING_DISTANCE_M`). Two separate distances are kept in the
   output so this stays transparent: `snap_avstand_m` (field coordinate
   to the drawn marker) and `elvenett_avstand_m` (field coordinate to
   the Elvenett edge the trace actually uses) -- on the real Arendal
   run, FKB-Vann placed 30 of 44 markers, 6 culverts still have a marker
   >50 m from their field coordinate, and 13 have an Elvenett edge >50 m
   away (a separate, usually larger set, since FKB-Vann can make the
   *marker* accurate without Elvenett having anything nearby to trace
   from at all).

   **Not every case is fixable this way, though.** Correcting the input
   point can only pick a better *existing* Elvenett edge -- it can't
   invent one where the network simply has a gap. For 13 of the 44, the
   nearest Elvenett edge is still more than `SUSPICIOUS_SNAP_DISTANCE_M`
   (50 m) from the field coordinate even after that correction, meaning
   the culvert isn't genuinely ON the stream that edge belongs to. Since
   it isn't really a barrier on that stream, it's excluded from the
   walk/colouring entirely: **it doesn't colour that distant edge
   red/orange, and it doesn't act as a stop for any other culvert's walk
   either** (earlier versions of this script got this wrong -- a
   culvert's dot could move to its correct FKB-Vann position while a
   now-unrelated Elvenett stretch stayed marked "blocked" by it, or
   another real barrier's reach got cut short by a phantom stop point).
   Its own `oppstrom_lengde_km`, `oppstrom_innsjo_km2`, and
   `prioriteringsscore` are left **blank, not computed at all** rather
   than a plausible-looking number from the wrong stream -- flagged
   `score_upalitelig` in the output, excluded from step 7's ranked
   report, and shown on the map as a culvert with a thick black dashed
   ring and no size-scaled dot (it falls back to a fixed radius, since
   there's no score to size it by). 7 of these 13 have FKB-Vann
   confirming real water within 30 m of the field coordinate -- so
   we're confident they're real barriers, just not on a stream Elvenett
   maps there; the other 6 lack even that confirmation, so the field
   coordinate itself might simply be off.

   **For those 7 FKB-confirmed culverts, step 4 also traces upstream on
   FKB-Vann itself** (if `--dtm`/`--hoyde-api` is given -- the same
   elevation source used for natural-barrier detection below), so they
   still get a real, computed answer instead of nothing. FKB-Vann
   carries no flow-direction data of its own (unlike Elvenett, digitized
   upstream-to-downstream), so direction is *inferred from elevation*:
   one lookup per touching FKB-Vann polygon (its centroid), with water
   assumed to flow from the higher-elevation polygon to the lower one.
   The walk itself works the same way as Elvenett's -- follow the
   directed graph upstream, stop at another barrier culvert's polygon --
   just at whole-polygon granularity (~10-50 m chunks) since FKB-Vann
   has no within-polygon position to cut at more precisely. Results:
   `oppstrom_fkb_areal_m2` (an area, since FKB-Vann is polygons, not the
   line-length `oppstrom_lengde_km` Elvenett gives) and
   `prioriteringsscore_fkb`, a 0-100 score -- but ranked **only among
   these FKB-traced culverts**, not blended into the main
   `prioriteringsscore` above: an area of coarse FKB-Vann polygons isn't
   really comparable to Elvenett's precise river-length figure, and
   inventing an exchange rate between them would have the same
   unfounded-precision problem this project already avoided once for
   river-length-vs-lake-area (see point 5 below). The traced polygons
   are coloured red/orange on the map the same way Elvenett's are (see
   step 3) -- on the real Arendal run, all 7 of 7 were traced
   successfully (elevation was known for all 1,457 FKB-Vann polygons),
   giving 9 coloured polygons in total; the areas involved are small
   (tens to under a thousand m2 each), which makes sense -- these are
   specifically the streams too small/disconnected for Elvenett to map
   at all, in either dataset.
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

*(The gradient classification was originally validated only against
small hand-built test rasters with known slopes in them -- 12%, 8%, and
3% steps, correctly sorted into "certain"/"cautious"/"not flagged" --
and the `--hoyde-api` plumbing only by mocking the API response,
because the environment this was first built in had no route to
Kartverket's service. **`--hoyde-api` has since been run for real** --
see the note below the API's own name for a real bug that blocked it
until now. On the real Arendal run: 33 confident natural barriers (stop
the walk) and 30 possible ones (flagged, don't stop it), out of 883
river segments.)*

**A real bug was hiding behind "never run against real data": the
elevation API's coordinate-system parameter was wrong.** The code sent
`koordsystemkode=4326`; Kartverket's `hoydedata` API actually expects
`koordsys=4326` -- every single request came back
`422 UNPROCESSABLE ENTITY`, silently returning no elevation for every
point (steps 2, 4, and 9 all made this same call). Since this had only
ever been tested by mocking the HTTP response, not a real call, nothing
caught the wrong parameter name until `--hoyde-api` was actually run
for the first time. Fixed in all three scripts; if you have an old
`data/processed/hoyde_cache*.json` from before this fix, delete it --
it's full of cached `null`s from the broken calls and will otherwise
make the fix look like it's still not returning data.

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
re-run. Also check the console output for two separate distances,
both against `SUSPICIOUS_SNAP_DISTANCE_M` (50 m):

- **`snap_avstand_m`** (field coordinate to the drawn marker) -- 6 of
  44 in the current Arendal run. These are worth a manual look: either
  a genuine coordinate error, or the culvert is on a stream too small
  for either Elvenett or FKB-Vann to include at all.
- **`elvenett_avstand_m`** (field coordinate to the Elvenett edge the
  upstream trace would start from) -- 13 of 44, a larger set than the
  above, since FKB-Vann can place the *marker* accurately without
  Elvenett having anything nearby to trace from. These are exactly the
  `score_upalitelig` culverts (see above): not genuinely on the stream
  Elvenett would trace from, so they're excluded from the walk and
  colouring entirely rather than computed from an unrelated stream, a
  genuine Elvenett network gap that snapping logic alone can't fix. 7
  of the 13 have FKB-Vann confirming real water right at the field
  point (definitely real barriers, just not on a stream Elvenett maps);
  the other 6 don't, so those might just have an inaccurate field
  coordinate.

**Step 3 draws the `snap_avstand_m` warning on the map:** a dashed line
from the original field coordinate to the point actually used, with a
small white/black dot marking the original -- so a coordinate that
lands in the middle of a lake, or nowhere near any mapped stream, is
immediately visible instead of silently trusted. Only shown beyond
50 m (`SNAP_WARNING_DISTANCE_M` in `scripts/03_lag_kart.py`) since a
few metres of GPS noise is normal and not worth flagging; the
`score_upalitelig` culverts get their own, separate black-ringed marker
style instead (see step 3), since their marker position itself isn't
the problem.

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

**Culverts flagged `score_upalitelig` by step 4 have no score to rank
by in the first place, so they're excluded from the ranking** -- their
Elvenett edge is too far from the field coordinate to genuinely be the
stream they're a barrier on, so step 4 leaves their priority score and
upstream-habitat figures blank rather than computing them from the
wrong, unrelated stream (see step 4). They're still real, mapped
barriers -- just not sorted or given a fabricated number here -- and
the report's summary section names them explicitly by site, noting
which have FKB-Vann confirming real water nearby (7) versus not (6), so
nothing is silently dropped. 13 of 44 in the current Arendal run.

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

### Step 8 -- (optional) cross-check against FKB-Vann

```bash
python scripts/08_sjekk_fkb_vann.py --fkb data/raw/fkb_vann/fkb_vann_omrade_arendal.shp --kommune Arendal
```

A ready-made Arendal-clipped export is already included at that path
(see "Now run and validated..." below) -- pass your own `--fkb` file
instead if you have a different/newer export.

**FKB-Vann** (Felles KartdataBase -- Vann) is Kartverket's detailed
hydrography layer -- captured by aerial photogrammetry, so it's
positionally more precise than Elvenett, but it's a cartographic
dataset, not a connected network graph with flow direction the way
Elvenett is. So it can't replace Elvenett for the upstream trace in
step 4 -- it can only *check* it (and, as of the change described in
step 4, also *correct which Elvenett point gets used*, though the
network structure itself always still comes from Elvenett).

**This script itself doesn't change the network, the map, or the
priority score** -- it's a read-only diagnostic (step 4 is a separate
script that now uses this same FKB-Vann file for real, see above). For
every barrier culvert it measures how far the field coordinate (and
separately, the point step 4 snapped to) is from the nearest FKB-Vann
water feature, and flags any culvert where the two datasets disagree by
more than 15 m at the point already in use -- worth a field look, and a
likely explanation for some of the culverts step 4 flags as snapping
far from any mapped stream. Results go to
`data/processed/kulvert_fkb_sjekk.csv`. Since a real export can cover a
much bigger area than one kommune, the script reads only a buffered box
around the culverts being checked, rather than the whole file.

**Where to get FKB-Vann:** Kartverket's national base map layer,
distributed through Geonorge (`nedlasting.geonorge.no`, needs a free
GeoID login) as SOSI/GML/shapefile per kommune, or via a regional portal
like Agder's own [agderkart.no](https://agderkart.no/agderkart). Get
the export for Arendal and pass its path with `--fkb`.

**Now run and validated against a real Kartverket/Geonorge export** --
a whole-Agder `område` (polygon/area) delivery, `fkb_vann_omrade`
(55,727 features: `Elv` river polygons, `Innsjø` lake polygons,
`Havflate` sea, excluded). The script auto-detects this variant and
compares distance to the nearest polygon instead of the nearest line
(0 if the point already falls inside one). It also still supports the
`linje` (centreline) delivery this was originally written for, though
that variant itself hasn't been run against a real export -- the
column/geometry detection is defensive either way: it looks for an
object-type column (commonly `objtype`) to keep only real water
features, but falls back to "use every feature of the matching
geometry type" with a clear console warning if that column isn't where
expected. If it guesses wrong on your actual file, the printed column
names and object-type values make it straightforward to fix.

The whole-Agder file was clipped down to a ~34 x 27 km box around
Arendal's culverts (`data/raw/fkb_vann/fkb_vann_omrade_arendal.shp`,
1,756 features) and that's what's committed to the repo, the same
kommune-scoped pattern as `data/raw/nve_elvenett/` and
`data/raw/nve_innsjo/` -- the full county file is ~550 MB, far too big
to check in (and the script only ever reads a small bounding box out of
whatever file you point it at anyway). On the real Arendal run: 19 of
44 barrier culverts were flagged as disagreeing with FKB-Vann by more
than 15 m at the point Elvenett snapped to -- but per the caveat above,
most of those are on streams too narrow for the `område` polygon
product to represent at all (confirmed by inspection: several flagged
culverts have a near-perfect Elvenett snap distance, under 10 m, with
the nearest actual FKB polygon 600-1000+ m away), not genuine
disagreements about where a mapped stream sits.

**Caveat found from the real run, specific to the `område` variant:**
FKB-Vann only digitizes a river as a polygon once it's wide enough --
narrow streams have no `Elv`/`Innsjø` polygon at all in this product
(only in the `linje` delivery). So a big disagreement number from an
`område`-type file often just means "no comparable FKB-Vann polygon
nearby," not a real positional conflict -- confirmed on the real
Arendal run, where several culverts with a near-perfect Elvenett snap
(under 10 m) still showed 400-1000+ m FKB "disagreements" simply
because the nearest river/lake polygon really was that far away. Treat
flags from this file with that in mind; the `linje` variant (streams of
every size, not just wide rivers) would be a more reliable source of
genuine disagreements if you can get it.

**FKB-Vann is also drawn directly on the map** (step 3 auto-detects
`data/raw/fkb_vann/fkb_vann_omrade_arendal.shp` and adds it as its own
switchable overlay, teal-coloured, next to Elvenett) so you can visually
compare the two networks and see where either has a stream the other
doesn't -- this is on top of, not instead of, the numeric check this
step does. This map used to also offer a live-WMS visual comparison
(`--fkb-wms-test`) -- confirmed not to work (the "Vann" layer name,
guessed at without a real route to Kartverket's WMS, came back blank on
a real run) -- and it's been removed outright now that the local-file
overlay above does the same job reliably. Drawing FKB-Vann's real
geometry directly also surfaced an important lesson: this data is
captured at sub-metre precision, so embedding it in the map balloons the
HTML file from 1.7 MB to ~28 MB and makes it noticeably slower to load
-- tried simplifying the geometry down to ~4 MB first, but the project
owner asked for full detail instead and confirmed the slower load is
worth it, so step 3 now embeds FKB-Vann at full precision, no
simplification. The same full-precision geometry is also what culvert
snapping (above) measures against, so the extra detail directly
improves marker accuracy too, not just what you see.

### Step 9 -- (optional) height profile of a whole vassdrag

```bash
python scripts/09_hoydeprofil.py --dtm path/to/dtm.tif --vassdrag Arendalsvassdraget
# or, without a downloaded DTM file:
python scripts/09_hoydeprofil.py --hoyde-api --vassdrag Arendalsvassdraget
```

Step 4's natural-barrier detection works per short river segment, which
makes it hard to eyeball against what you already know about a real
river. This script instead walks a WHOLE named vassdrag from mouth to
source and draws an actual elevation profile (PNG), marking every point
where the same smoothed gradient used in step 4
(`NATURAL_GRADIENT_CERTAIN` = 10%, `NATURAL_GRADIENT_CAUTIOUS` = 7%,
smoothed over the same 100 m window) would flag a likely or possible
natural waterfall/rapid -- a way to sanity-check the method against a
river whose real waterfalls you already know, not a different
detection method.

Since NVE's Elvenett only names a minority of segments (and, checked
directly, filtering on that name alone leaves gaps -- some connecting
stretches carry a different name or none), this script filters on the
more complete `hierarki` field instead and finds the *longest path*
through the matched segments (by river length) -- this reliably picks
out the single main-stem line from mouth to furthest headwater without
needing to trust segment names or the digitisation direction. For
Arendalsvassdraget this finds a 17.3 km main stem through 52 segments,
correctly bridging naming gaps that a plain name-filter misses.

**Most precise elevation source:** `--dtm` with a downloaded GeoTIFF
from Kartverket's <https://hoydedata.no/> -- their actual national
terrain model ("Nasjonal detaljert hoydemodell"), a 1x1 m laser-scanned
grid nationally (finer in some specifically surveyed areas). Reading a
downloaded raster directly also lets you sample as densely as you want
along the river for free, unlike the point API. `--hoyde-api` (the same
Kartverket web service steps 2 and 4 use) queries the *same* underlying
height model, just one point at a time over the internet -- use it if
you'd rather not download a DTM file first.

**Now run for real, with `--hoyde-api`, after fixing the elevation-API
bug described above.** Originally only tested with a synthetic DTM (an
8 m drop over 30 m injected into a raster covering the real
Arendalsvassdraget main-stem geometry) -- that synthetic test confirmed
the main-stem finding, sampling, and candidate-detection logic all work
correctly, but said nothing about whether the *method* flags real
waterfalls, only that the code runs.

The real run found the main stem (52 segments, 17.3 km, out of 487
segments matching "Arendalsvassdraget" in `hierarki` -- 26 disconnected
pieces were found and correctly excluded, using only the largest
connected piece) and produced a genuinely clean-looking result: a flat
~39 m plateau from km 4-8.5 (almost certainly a lake), then a sharp,
obvious step from ~48 m to ~123 m between km 12.5 and 14 -- and the
method correctly flagged that step and nowhere else: **4 confident +
4 possible candidates, all of them right on that one step, zero false
positives on the flat stretches either side.** See
`output/hoydeprofil_arendalsvassdraget.png`. This doesn't confirm any
specific named waterfall (that needs local knowledge this project
doesn't have), but it's a strong sign the smoothed-gradient method
genuinely tracks real terrain, not just the synthetic test case.

## Setup

```bash
pip install -r requirements.txt
python scripts/01_rens_kulvertdata.py
python scripts/02_hent_hoydedata.py       # optional, needs internet, can take a while
python scripts/04_koble_til_elvenett.py --river data/raw/nve_elvenett/Elv_Elvenett.shp --kommune Arendal --innsjo data/raw/nve_innsjo/Innsjo_Innsjo.shp --fkb data/raw/fkb_vann/fkb_vann_omrade_arendal.shp --hoyde-api
python scripts/05_legg_til_innsjoer.py    # optional, lake map layer
python scripts/06_legg_til_feltdata.py --kommune Arendal   # optional, real field-assessment data
python scripts/03_lag_kart.py
python scripts/07_lag_rapport.py --kommune Arendal --antall 5   # optional, Word report + draft søknad
```

A ready-made map (Arendal, with the coloured river network AND real
natural-barrier detection from `--hoyde-api`) is already included at
`output/agder_kulvert_kart.html`, so you can open it right away and
re-run the pipeline later if you want to add height data, cover another
kommune, or refresh the source data.

**You need an internet connection when you *open* the map** (not when
you build it) -- the background map images (terrain, streets,
satellite) are loaded live from OpenTopoMap / OpenStreetMap / Esri each
time you view it.

## Notes and things to check

- **If a background layer (OpenTopoMap, satellite, ...) shows blank/grey:**
  most likely either no internet connection *in the browser viewing the
  map* (these are loaded live -- see above), or a network/firewall that
  blocks the specific tile domains (`tile.opentopomap.org`,
  `arcgisonline.com`, `tile.openstreetmap.org`, `cache.kartverket.no`) --
  worth checking on a different network if you're on a locked-down
  office connection. One real bug this project did have and has fixed:
  zooming in past a layer's own maximum tile resolution used to make it
  vanish entirely rather than just get blurry (e.g. OpenTopoMap only has
  real tiles up to zoom 17) -- `max_native_zoom` is now set on every
  base layer so it keeps showing the most detailed tile it has, scaled
  up, instead of going blank past that point.
- **Elvenett rivers sometimes stop abruptly, with nothing mapped further
  upstream.** Checked directly against the data: Arendal's Elvenett
  network has 247 dangling (dead-end) line endpoints. Cross-referencing
  each against FKB-Vann's coverage, 211 of the 247 aren't near *any*
  FKB-Vann polygon either (median distance 370 m) -- meaning even
  Kartverket's more detailed dataset doesn't map a stream any further
  there, so these are almost certainly genuine headwater termini (small
  streams too narrow for either official dataset to capture), not a bug
  in this project. The other 36 of 247 do sit within 10 m of an FKB-Vann
  polygon, so FKB-Vann may have a bit more detail there than Elvenett's
  line reaches -- visible on the map by comparing the FKB-Vann overlay
  (step 8/3) against Elvenett at those spots. Splicing FKB-Vann directly
  into the upstream-trace graph (so the red/orange colouring would
  continue past these gaps) was considered and deliberately not done --
  FKB-Vann carries no flow-direction/connectivity data, so building a
  reliable network out of it is a real engineering effort with real risk
  of introducing subtle errors, not a quick fix.
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
  "opened up". **The shipped map now includes this** -- step 4 is run
  with `--hoyde-api` (see Setup below), which found 33 confident and 30
  possible natural barriers on the real Arendal river network. A DTM
  file (`--dtm`) would be faster and work offline, but hasn't been
  tried against real Arendal data yet -- worth doing if you get one, as
  a cross-check against the API-based result.
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
data/raw/fkb_vann/          FKB-Vann export, clipped to Arendal (step 4 snapping + step 8 cross-check + step 3 map layer)
data/raw/kommunegrense/     Arendal's administrative boundary, from Kartverket's Kommuneinfo API (step 3 outline)
data/processed/             cleaned CSV/GeoJSON + coloured river network + lakes + field data (generated by scripts)
scripts/                    the ten pipeline steps, run in order
output/                     the final map (agder_kulvert_kart.html) + the prioritisation report (prioriteringsrapport.docx)
```

## Wishlist for better source data

If you're asking a GIS colleague for anything, these are the gaps this
project actually ran into (in rough order of impact):

- **A real elevation raster (DTM) for Arendal.** `--hoyde-api` now works
  and has confirmed Kartverket's høydedata service has good coverage
  here (elevation known for 100% of both the Elvenett segments and the
  FKB-Vann polygons sampled -- see step 4), but it fetches one point at
  a time over the internet. A downloaded DTM `.tif` would be faster and
  offline-capable, and worth getting as a cross-check against the
  API-based natural-barrier result.
- **Vann-Nett water body polygons with the "Anadrom fisk" attribute**
  for Arendal's streams/lakes -- this is the authoritative national
  register for where anadromous fish are actually present, and would
  replace the much sparser "Anadrom strekning?" field this project has
  today (only 9 of 44 barrier culverts have a definite answer; see step
  6). It would let the priority score account for fish presence, not
  just reachable habitat area.
- **Corrected coordinates for the 6 culverts whose marker still sits
  >50 m from their field coordinate** even after the FKB-Vann-informed
  snap (step 4's console output lists them, and they're shown as dashed
  lines on the map) -- FKB-Vann doesn't confirm water nearby for these
  either, so the field GPS point may simply be off, or the culvert is on
  a stream too small for either Elvenett or FKB-Vann to map. These are
  also 6 of the 13 `score_upalitelig` culverts (their marker AND their
  score both need attention); the other 7 have an accurate marker
  (FKB-Vann confirms real water right there) but still no nearby
  Elvenett edge to trace a score from -- those would benefit most from
  an Elvenett update or a manually-traced upstream length.
- **Lake depth/bathymetry data**, if any exists for the 201 lakes in
  the Arendal export -- NVE's own lake layer has no bathymetry on file
  for any of them (see step 5), so the score currently uses surface
  area only, treating a shallow pond the same as a deep lake of equal
  area.
