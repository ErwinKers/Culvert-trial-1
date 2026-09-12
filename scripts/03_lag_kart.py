"""
Step 3: build the actual interactive map, and save it as a single HTML
file you can open in any web browser (double-click it, no installation
needed to VIEW it -- only to build it).

This map only shows culverts that are actually a problem for fish
migration: "Absolutt" (total barrier) and "Partiell" (partial barrier).
The other categories (not a barrier, not assessed, etc.) aren't
relevant to this map's purpose, so they're left out entirely.

What ends up on the map
------------------------
* Background ("base") map you can switch between:
    - OpenTopoMap: a terrain map with contour lines and hillshading, so
      you can see the shape of the landscape (this is our "height data"
      layer -- you can visually tell uphill from downhill) and it also
      draws rivers and streams.
    - OpenStreetMap: an ordinary street map, useful for orientation
      (roads, place names).
    - Esri World Imagery: satellite photos.
  These background maps are drawn by the tile servers themselves, live,
  in your browser, whenever you have internet access and open the map --
  this script does not need internet to build the file.

* One dot per barrier culvert, coloured red (total barrier) or orange
  (partial barrier). If you ran step 4 (river network linking), the dot
  sits at the point snapped onto the nearest mapped stream, which is
  more reliable than the raw field coordinate; click a dot to see both
  the snapped and original position, and how far apart they are.

* If you ran step 4: the stretch of river/stream network upstream of
  each barrier, coloured the same way (red/orange), so you can see --
  and, from the popup, read off in km -- how much habitat would open
  up if that particular culvert were fixed.

* A legend explaining the colours, and a layer switcher (top right) so
  you can turn categories or background maps on/off.

Usage
-----
    python scripts/03_lag_kart.py
"""

import json
from pathlib import Path

import folium
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
IN_CSV_CANDIDATES = [
    ROOT / "data" / "processed" / "kulvert_punkter_oppstrom.csv",
    ROOT / "data" / "processed" / "kulvert_punkter_med_hoyde.csv",
    ROOT / "data" / "processed" / "kulvert_punkter.csv",
]
IN_GEOJSON_UPSTREAM = ROOT / "data" / "processed" / "oppstroms_elvenett.geojson"
OUT_HTML = ROOT / "output" / "agder_kulvert_kart.html"

# Only these two categories are actual migration barriers -- the rest
# ("Ikke hinder", "Ikke angitt", ...) are left off this map on purpose.
BARRIER_ORDER = ["Absolutt", "Partiell"]
BARRIER_LABELS = {
    "Absolutt": "Totalt vandringshinder",
    "Partiell": "Delvis vandringshinder",
}
BARRIER_COLORS = {"Absolutt": "#d7191c", "Partiell": "#fdae61"}


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
    df = df[df["barrier_category"].isin(BARRIER_ORDER)].copy()
    print(f"Showing {len(df)} of {before} culverts (Absolutt/Partiell only)")
    return df


def load_upstream_geojson():
    if not IN_GEOJSON_UPSTREAM.exists():
        return None
    with open(IN_GEOJSON_UPSTREAM, "r", encoding="utf-8") as f:
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
        html += field("Oppstrøms elvestrekning som åpnes", row.get("oppstrom_lengde_km"), " km")
        html += field("Avstand kartlagt punkt -> elvenett", row.get("snap_avstand_m"), " m")
    html += field("Kommentar", row.get("kommentar"))
    html += "</div>"
    return html


def marker_radius(row, has_height):
    if not has_height:
        return 6
    diff = row.get("elevation_diff_m")
    if pd.isna(diff):
        return 6
    # Bigger height drop -> bigger dot. Clamp so one huge outlier
    # doesn't dwarf everything else on the map.
    return max(5, min(5 + diff, 16))


def add_base_layers(m):
    folium.TileLayer(
        tiles="https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
        attr=(
            "Map data: &copy; OpenStreetMap contributors, SRTM | "
            "Map style: &copy; OpenTopoMap (CC-BY-SA)"
        ),
        name="OpenTopoMap (terreng/høyde + elver)",
        max_zoom=17,
        overlay=False,
        control=True,
    ).add_to(m)

    folium.TileLayer(
        tiles="OpenStreetMap",
        name="OpenStreetMap (vanlig kart)",
        overlay=False,
        control=True,
    ).add_to(m)

    folium.TileLayer(
        tiles=(
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "World_Imagery/MapServer/tile/{z}/{y}/{x}"
        ),
        attr="Tiles &copy; Esri",
        name="Esri satellittbilde",
        overlay=False,
        control=True,
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


def add_legend(m, has_upstream):
    rows = ""
    for cat in BARRIER_ORDER:
        rows += (
            f"<div style='margin:2px 0'>"
            f"<span style='display:inline-block;width:12px;height:12px;"
            f"border-radius:50%;background:{BARRIER_COLORS[cat]};margin-right:6px'></span>"
            f"{BARRIER_LABELS[cat]} (kulvert)</div>"
        )
    if has_upstream:
        for cat in BARRIER_ORDER:
            rows += (
                f"<div style='margin:2px 0'>"
                f"<span style='display:inline-block;width:16px;height:3px;"
                f"background:{BARRIER_COLORS[cat]};margin-right:6px;vertical-align:middle'></span>"
                f"Elv/bekk oppstrøms {BARRIER_LABELS[cat].lower()}</div>"
            )

    legend_html = f"""
    <div style="
        position: fixed; bottom: 30px; left: 30px; z-index: 9999;
        background: white; padding: 10px 14px; border: 1px solid #999;
        border-radius: 6px; font-size: 13px; box-shadow: 2px 2px 6px rgba(0,0,0,0.3);">
        <b>Vandringshinder for fisk</b><br>
        {rows}
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))


def add_upstream_layers(m, geojson):
    """One FeatureGroup per barrier category, so the red/orange upstream
    river stretches can be toggled independently of the culvert dots."""
    groups = {
        cat: folium.FeatureGroup(name=f"Elvenett oppstrøms: {BARRIER_LABELS[cat]}")
        for cat in BARRIER_ORDER
    }
    for feature in geojson["features"]:
        cat = feature["properties"].get("kategori")
        group = groups.get(cat)
        if group is None:
            continue
        folium.GeoJson(
            feature,
            style_function=lambda _f, color=feature["properties"]["farge"]: {
                "color": color,
                "weight": 4,
                "opacity": 0.85,
            },
        ).add_to(group)
    for group in groups.values():
        group.add_to(m)


def main():
    df = load_data()
    has_height = "elevation_diff_m" in df.columns
    has_snap = "lat_snappet" in df.columns
    upstream_geojson = load_upstream_geojson()

    positions = df.apply(lambda r: marker_position(r, has_snap), axis=1, result_type="expand")
    df["_map_lat"], df["_map_lon"] = positions[0], positions[1]

    center_lat = df["_map_lat"].mean()
    center_lon = df["_map_lon"].mean()

    m = folium.Map(location=[center_lat, center_lon], zoom_start=9, tiles=None)
    add_base_layers(m)

    if upstream_geojson is not None:
        add_upstream_layers(m, upstream_geojson)
    else:
        print("(no data/processed/oppstroms_elvenett.geojson found -- run")
        print(" scripts/04_koble_til_elvenett.py to add the upstream river layers)")

    groups = {cat: folium.FeatureGroup(name=f"Kulverter: {BARRIER_LABELS[cat]}") for cat in BARRIER_ORDER}

    for _, row in df.iterrows():
        cat = row.get("barrier_category")
        group = groups.get(cat)
        if group is None:
            continue

        folium.CircleMarker(
            location=[row["_map_lat"], row["_map_lon"]],
            radius=marker_radius(row, has_height),
            color=BARRIER_COLORS[cat],
            fill=True,
            fill_color=BARRIER_COLORS[cat],
            fill_opacity=0.9,
            weight=1,
            popup=folium.Popup(build_popup_html(row, has_height, has_snap), max_width=300),
        ).add_to(group)

    for group in groups.values():
        group.add_to(m)

    add_legend(m, upstream_geojson is not None)
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
