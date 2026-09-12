"""
Step 3: build the actual interactive map, and save it as a single HTML
file you can open in any web browser (double-click it, no installation
needed to VIEW it -- only to build it).

This map only covers ARENDAL kommune (see KOMMUNE_FILTER below), and
only shows culverts that are actually a problem for fish migration:
"Absolutt" (total barrier) and "Partiell" (partial barrier). The other
categories (not a barrier, not assessed, etc.) aren't relevant to this
map's purpose, so they're left out entirely.

What ends up on the map
------------------------
* Background ("base") map you can switch between:
    - OpenTopoMap: a terrain map with contour lines and hillshading, so
      you can see the shape of the landscape (this is our "height data"
      layer -- you can visually tell uphill from downhill).
    - OpenStreetMap: an ordinary street map, useful for orientation
      (roads, place names).
    - Esri World Imagery: satellite photos.
  These background maps are drawn by the tile servers themselves, live,
  in your browser, whenever you have internet access and open the map --
  this script does not need internet to build the file.

* If you ran step 4: the WHOLE Arendal river/stream network (NVE's
  real Elvenett data, not just a background picture), coloured:
    - red    = upstream of an "Absolutt" (total) barrier
    - orange = upstream of a "Partiell" (partial) barrier
    - blue   = not affected -- either nowhere near a barrier, or
      downstream of one (a barrier only blocks upward passage, so fish
      already reach everything below it fine)

* One dot per barrier culvert, coloured red (total) or orange
  (partial). If you ran step 4, the dot sits at the point snapped onto
  the nearest mapped stream, which is more reliable than the raw field
  coordinate; click a dot to see both the snapped and original
  position, how far apart they are, and how many km of river would
  open up if that culvert were fixed.

* A legend explaining the colours, and a layer switcher (top right) so
  you can turn layers or background maps on/off.

Usage
-----
    python scripts/03_lag_kart.py
"""

import json
import math
from pathlib import Path

import folium
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
IN_CSV_CANDIDATES = [
    ROOT / "data" / "processed" / "kulvert_punkter_oppstrom.csv",
    ROOT / "data" / "processed" / "kulvert_punkter_med_hoyde.csv",
    ROOT / "data" / "processed" / "kulvert_punkter.csv",
]
IN_GEOJSON_RIVERS = ROOT / "data" / "processed" / "elvenett_farget.geojson"
IN_GEOJSON_NATURAL = ROOT / "data" / "processed" / "naturlige_hindre.geojson"
IN_GEOJSON_WIDTH = ROOT / "data" / "processed" / "elvenett_egenskaper.geojson"
IN_GEOJSON_LAKES = ROOT / "data" / "processed" / "innsjoer.geojson"
OUT_HTML = ROOT / "output" / "agder_kulvert_kart.html"

NATURAL_TIER_LABELS = {
    "sikker": "Sannsynlig naturlig vandringshinder",
    "mulig": "Mulig naturlig vandringshinder (usikker)",
}
NATURAL_TIER_COLORS = {"sikker": "#7a0177", "mulig": "#c994c7"}

# This map currently only covers one kommune, matching the NVE river
# network export used in step 4. Change this (and re-run step 4 with a
# matching --kommune / river file) to cover a different area.
KOMMUNE_FILTER = "Arendal"

# Only these two categories are actual migration barriers -- the rest
# ("Ikke hinder", "Ikke angitt", ...) are left off this map on purpose.
BARRIER_ORDER = ["Absolutt", "Partiell"]
BARRIER_LABELS = {
    "Absolutt": "Totalt vandringshinder",
    "Partiell": "Delvis vandringshinder",
}
BARRIER_COLORS = {"Absolutt": "#d7191c", "Partiell": "#fdae61"}
BLUE = "#2c7fb8"


def load_data():
    for path in IN_CSV_CANDIDATES:
        if path.exists():
            print(f"Using {path}")
            df = pd.read_csv(path)
            break
    else:
        raise SystemExit("Run scripts/01_rens_kulvertdata.py first.")

    if path.name != "kulvert_punkter_oppstrom.csv":
        print("(run scripts/04_koble_til_elvenett.py to snap culverts onto the")
        print(" real river network and see how much habitat opens up upstream)")

    before = len(df)
    df = df[(df["kommune"] == KOMMUNE_FILTER) & (df["barrier_category"].isin(BARRIER_ORDER))].copy()
    print(f"Showing {len(df)} of {before} culverts ({KOMMUNE_FILTER}, Absolutt/Partiell only)")
    return df


def load_geojson(path):
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def marker_position(row, has_snap):
    if has_snap and pd.notna(row.get("lat_snappet")) and pd.notna(row.get("lon_snappet")):
        return row["lat_snappet"], row["lon_snappet"]
    return row["lat_ned"], row["lon_ned"]


def build_popup_html(row, has_height, has_snap):
    def field(label, value, unit=""):
        if pd.isna(value) or str(value).strip() in ("", "nan"):
            return ""
        return f"<b>{label}:</b> {value}{unit}<br>"

    html = "<div style='font-size: 13px; max-width: 260px'>"
    html += field("Sted", row.get("stedsnavn"))
    html += field("Kommune", row.get("kommune"))
    html += field("Vassdrag", row.get("vassdrag"))
    html += field("Regine", row.get("regine"))
    html += "<hr style='margin:4px 0'>"
    html += field("Vurdering (vandringshinder)", row.get("barrier_label"))
    html += field("Opprinnelig tekst", row.get("vurdering_raw"))
    html += field("Beskrivelse av problem", row.get("problem_beskrivelse"))
    html += field("Diameter", row.get("diameter_cm"), " cm")
    html += field("Lengde", row.get("lengde_m"), " m")
    if has_height:
        html += field("Høyde nedstrøms", row.get("elevation_ned_m"), " moh")
        html += field("Høyde oppstrøms", row.get("elevation_opp_m"), " moh")
        html += field("Høydeforskjell", row.get("elevation_diff_m"), " m")
    if has_snap:
        html += "<hr style='margin:4px 0'>"
        html += field("Prioriteringsscore (0-100)", row.get("prioriteringsscore"))
        html += field("Oppstrøms elvestrekning som åpnes", row.get("oppstrom_lengde_km"), " km")
        html += field("Avstand kartlagt punkt -> elvenett", row.get("snap_avstand_m"), " m")
    html += field("Kommentar", row.get("kommentar"))
    html += "</div>"
    return html


def marker_radius(row, has_score, has_height):
    # Priority score (how much habitat opens up) is the most useful
    # thing to show at a glance, so it takes priority over elevation
    # for sizing the dot: a bigger dot means fixing that culvert would
    # unlock more river for anadromous fish.
    if has_score and pd.notna(row.get("prioriteringsscore")):
        score = row["prioriteringsscore"]
        return 5 + (score / 100) * 12  # ranges roughly 5-17
    if has_height and pd.notna(row.get("elevation_diff_m")):
        diff = row["elevation_diff_m"]
        return max(5, min(5 + diff, 16))
    return 6


def add_base_layers(m):
    # NOTE: folium/Leaflet stacks base layers in the order they're added
    # and shows whichever ones have show=True on top of each other -- so
    # exactly ONE of these must be show=True, or you'll see whichever
    # was added last (which is how this map used to default to the
    # aerial photo layer without anyone asking for that). OpenTopoMap is
    # the intended default: a real map style (not a photo), with contour
    # lines/hillshading for terrain.
    folium.TileLayer(
        tiles="https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
        attr=(
            "Map data: &copy; OpenStreetMap contributors, SRTM | "
            "Map style: &copy; OpenTopoMap (CC-BY-SA)"
        ),
        name="OpenTopoMap (terreng/høyde)",
        max_zoom=17,
        overlay=False,
        control=True,
        show=True,
    ).add_to(m)

    folium.TileLayer(
        tiles="OpenStreetMap",
        name="OpenStreetMap (vanlig kart)",
        overlay=False,
        control=True,
        show=False,
    ).add_to(m)

    folium.TileLayer(
        tiles=(
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "World_Imagery/MapServer/tile/{z}/{y}/{x}"
        ),
        attr="Tiles &copy; Esri",
        name="Esri satellittbilde (flyfoto)",
        overlay=False,
        control=True,
        show=False,
    ).add_to(m)

    # Kartverket's own topographic map is normally the most detailed
    # option for Norway specifically, but tile services move/rename
    # layers occasionally. If this layer stays blank/grey when you open
    # the map, look up the current WMTS address at
    # https://kartverket.no/api-og-data/apne-kartdata and swap it in
    # here -- everything else on the map will keep working regardless.
    folium.TileLayer(
        tiles="https://cache.kartverket.no/v1/wmts/1.0.0/topo/default/webmercator/{z}/{y}/{x}.png",
        attr="Kartverket",
        name="Kartverket topografisk (kan trenge oppdatert URL)",
        overlay=False,
        control=True,
        show=False,
    ).add_to(m)


def add_legend(m, has_rivers, has_score, has_natural):
    rows = ""
    if has_score:
        rows += (
            "<div style='margin:2px 0 6px 0'>Størrelse på prikk = "
            "prioriteringsscore (større = mer elv åpnes opp)</div>"
        )
    for cat in BARRIER_ORDER:
        rows += (
            f"<div style='margin:2px 0'>"
            f"<span style='display:inline-block;width:12px;height:12px;"
            f"border-radius:50%;background:{BARRIER_COLORS[cat]};margin-right:6px'></span>"
            f"{BARRIER_LABELS[cat]} (kulvert)</div>"
        )
    if has_rivers:
        river_rows = [
            (BARRIER_COLORS["Absolutt"], "Elv/bekk oppstrøms totalt vandringshinder"),
            (BARRIER_COLORS["Partiell"], "Elv/bekk oppstrøms delvis vandringshinder"),
            (BLUE, "Elv/bekk ikke påvirket / nedstrøms for hinder"),
        ]
        for color, label in river_rows:
            rows += (
                f"<div style='margin:2px 0'>"
                f"<span style='display:inline-block;width:16px;height:3px;"
                f"background:{color};margin-right:6px;vertical-align:middle'></span>"
                f"{label}</div>"
            )
    if has_natural:
        for tier, label in NATURAL_TIER_LABELS.items():
            color = NATURAL_TIER_COLORS[tier]
            rows += (
                f"<div style='margin:2px 0'>"
                f"<span style='display:inline-block;width:0;height:0;"
                f"border-left:6px solid transparent;border-right:6px solid transparent;"
                f"border-bottom:11px solid {color};margin-right:6px;vertical-align:middle'></span>"
                f"{label}</div>"
            )

    legend_html = f"""
    <div style="
        position: fixed; bottom: 30px; left: 30px; z-index: 9999;
        background: white; padding: 10px 14px; border: 1px solid #999;
        border-radius: 6px; font-size: 13px; box-shadow: 2px 2px 6px rgba(0,0,0,0.3);">
        <b>Vandringshinder for fisk -- {KOMMUNE_FILTER}</b><br>
        {rows}
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))


def add_river_layer(m, geojson):
    group = folium.FeatureGroup(name=f"Elvenett ({KOMMUNE_FILTER})")
    folium.GeoJson(
        geojson,
        style_function=lambda feature: {
            "color": feature["properties"]["farge"],
            "weight": 4 if feature["properties"]["farge"] != BLUE else 2,
            "opacity": 0.85,
        },
        tooltip=folium.GeoJsonTooltip(fields=["elvenavn"], aliases=["Elv/bekk:"]),
    ).add_to(group)
    group.add_to(m)


def discharge_color(q_m3s):
    """Light -> dark blue on a log scale, since discharge in this
    dataset spans several orders of magnitude (a trickle to a major
    river)."""
    low, high = -2, 2.2  # log10(0.01) .. log10(~160)
    t = (math.log10(max(q_m3s, 0.01)) - low) / (high - low)
    t = min(1.0, max(0.0, t))
    light, dark = (222, 235, 247), (8, 48, 107)
    rgb = [int(light[i] + (dark[i] - light[i]) * t) for i in range(3)]
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


def add_width_layer(m, geojson):
    """The estimated river-width 'ribbons' -- an area instead of a
    plain line, coloured by discharge. Added before the barrier-colour
    river layer so that layer's lines still draw crisply on top."""
    group = folium.FeatureGroup(name="Elv - anslått bredde og vannføring", show=True)
    folium.GeoJson(
        geojson,
        style_function=lambda feature: {
            "fillColor": discharge_color(feature["properties"]["vannforing_m3s"]),
            "color": discharge_color(feature["properties"]["vannforing_m3s"]),
            "weight": 0.5,
            "fillOpacity": 0.55,
        },
        tooltip=folium.GeoJsonTooltip(
            fields=["elvenavn", "vannforing_m3s", "bredde_est_m", "hastighet_est_ms", "nedborfelt_km2"],
            aliases=[
                "Elv/bekk:",
                "Vannføring (m3/s):",
                "Anslått bredde (m):",
                "Anslått hastighet (m/s):",
                "Nedbørfelt (km2):",
            ],
        ),
    ).add_to(group)
    group.add_to(m)


def add_lake_layer(m, geojson):
    group = folium.FeatureGroup(name="Innsjøer", show=True)
    fields = [f for f in ["navn", "areal_km2"] if geojson["features"] and f in geojson["features"][0]["properties"]]
    folium.GeoJson(
        geojson,
        style_function=lambda feature: {"fillColor": "#4292c6", "color": "#2171b5", "weight": 1, "fillOpacity": 0.6},
        tooltip=folium.GeoJsonTooltip(fields=fields, aliases=["Navn:", "Areal (km2):"][: len(fields)]) if fields else None,
    ).add_to(group)
    group.add_to(m)


def natural_barrier_icon(tier):
    color = NATURAL_TIER_COLORS[tier]
    filled = "1" if tier == "sikker" else "0.35"
    size = 16 if tier == "sikker" else 13
    html = (
        f'<div style="width:0;height:0;'
        f"border-left:{size // 2}px solid transparent;"
        f"border-right:{size // 2}px solid transparent;"
        f"border-bottom:{size}px solid {color};"
        f'opacity:{filled};filter:drop-shadow(0 0 1px white);"></div>'
    )
    return folium.DivIcon(html=html, icon_size=(size, size), icon_anchor=(size // 2, size))


def add_natural_barrier_layer(m, geojson):
    groups = {
        tier: folium.FeatureGroup(name=f"Naturlige hindre: {label}")
        for tier, label in NATURAL_TIER_LABELS.items()
    }
    for feature in geojson["features"]:
        tier = feature["properties"]["tier"]
        group = groups.get(tier)
        if group is None:
            continue
        lon, lat = feature["geometry"]["coordinates"][:2]
        name = feature["properties"].get("elvenavn")
        name = name if name and str(name).lower() != "nan" else "(ukjent)"
        popup_html = (
            f"<b>{NATURAL_TIER_LABELS[tier]}</b><br>"
            f"Elv/bekk: {name}<br>"
            f"Beregnet gradient: {feature['properties']['gradient_pct']}%"
            f" (glattet over ~100 m elvelengde)"
        )
        folium.Marker(
            location=[lat, lon],
            icon=natural_barrier_icon(tier),
            popup=folium.Popup(popup_html, max_width=260),
        ).add_to(group)
    for group in groups.values():
        group.add_to(m)


def main():
    df = load_data()
    has_height = "elevation_diff_m" in df.columns
    has_snap = "lat_snappet" in df.columns
    has_score = "prioriteringsscore" in df.columns
    river_geojson = load_geojson(IN_GEOJSON_RIVERS)
    natural_geojson = load_geojson(IN_GEOJSON_NATURAL)
    width_geojson = load_geojson(IN_GEOJSON_WIDTH)
    lake_geojson = load_geojson(IN_GEOJSON_LAKES)

    positions = df.apply(lambda r: marker_position(r, has_snap), axis=1, result_type="expand")
    df["_map_lat"], df["_map_lon"] = positions[0], positions[1]

    center_lat = df["_map_lat"].mean()
    center_lon = df["_map_lon"].mean()

    m = folium.Map(location=[center_lat, center_lon], zoom_start=11, tiles=None)
    add_base_layers(m)

    if width_geojson is not None:
        add_width_layer(m, width_geojson)
    else:
        print("(no data/processed/elvenett_egenskaper.geojson found -- run")
        print(" scripts/05_hent_elveegenskaper.py to add discharge/width)")

    if lake_geojson is not None:
        add_lake_layer(m, lake_geojson)

    if river_geojson is not None:
        add_river_layer(m, river_geojson)
    else:
        print("(no data/processed/elvenett_farget.geojson found -- run")
        print(" scripts/04_koble_til_elvenett.py to add the coloured river network)")

    if natural_geojson is not None and natural_geojson["features"]:
        add_natural_barrier_layer(m, natural_geojson)

    groups = {cat: folium.FeatureGroup(name=f"Kulverter: {BARRIER_LABELS[cat]}") for cat in BARRIER_ORDER}

    for _, row in df.iterrows():
        cat = row.get("barrier_category")
        group = groups.get(cat)
        if group is None:
            continue

        folium.CircleMarker(
            location=[row["_map_lat"], row["_map_lon"]],
            radius=marker_radius(row, has_score, has_height),
            color=BARRIER_COLORS[cat],
            fill=True,
            fill_color=BARRIER_COLORS[cat],
            fill_opacity=0.9,
            weight=1,
            popup=folium.Popup(build_popup_html(row, has_height, has_snap), max_width=300),
        ).add_to(group)

    for group in groups.values():
        group.add_to(m)

    add_legend(m, river_geojson is not None, has_score, natural_geojson is not None and bool(natural_geojson["features"]))
    folium.LayerControl(collapsed=False).add_to(m)

    # Zoom to fit all the points instead of a fixed zoom level.
    bounds = [[df["_map_lat"].min(), df["_map_lon"].min()], [df["_map_lat"].max(), df["_map_lon"].max()]]
    m.fit_bounds(bounds)

    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(OUT_HTML))
    print(f"Saved map to {OUT_HTML}")
    print("Open this file in a web browser to view it.")


if __name__ == "__main__":
    main()
