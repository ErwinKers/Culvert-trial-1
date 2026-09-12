"""
Step 3: build the actual interactive map, and save it as a single HTML
file you can open in any web browser (double-click it, no installation
needed to VIEW it -- only to build it).

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

* One dot per culvert, at the downstream point, coloured by the
  migration-barrier category we worked out in step 1 (red = total
  barrier, orange = partial, green = not a barrier, etc.). Click a dot
  to see the details (place name, river, comments, ...).

* A thin line from the downstream point to the upstream point of each
  culvert, so you can see exactly where the crossing is; if you ran
  step 2 (height data), this line's thickness reflects the elevation
  drop between the two points.

* A legend explaining the colours, and a layer switcher (top right) so
  you can turn categories or background maps on/off.

Usage
-----
    python scripts/03_lag_kart.py
"""

from pathlib import Path

import folium
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
IN_CSV_WITH_HEIGHT = ROOT / "data" / "processed" / "kulvert_punkter_med_hoyde.csv"
IN_CSV_BASE = ROOT / "data" / "processed" / "kulvert_punkter.csv"
OUT_HTML = ROOT / "output" / "agder_kulvert_kart.html"

# Same colours/labels as in step 1 -- kept here too so this script can
# also be read and understood on its own.
BARRIER_ORDER = [
    "Absolutt",
    "Partiell",
    "Nedstrøms hinder",
    "Ikke hinder",
    "Neppe fiskeførende",
    "Ikke angitt",
]


def load_data():
    if IN_CSV_WITH_HEIGHT.exists():
        print(f"Using data with elevation: {IN_CSV_WITH_HEIGHT}")
        return pd.read_csv(IN_CSV_WITH_HEIGHT)
    print(f"No elevation data found, using: {IN_CSV_BASE}")
    print("(run scripts/02_hent_hoydedata.py first if you want height info)")
    return pd.read_csv(IN_CSV_BASE)


def build_popup_html(row, has_height):
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


def add_legend(m):
    rows = ""
    colors = {
        "Absolutt": "#d7191c",
        "Partiell": "#fdae61",
        "Nedstrøms hinder": "#984ea3",
        "Ikke hinder": "#1a9641",
        "Neppe fiskeførende": "#2c7fb8",
        "Ikke angitt": "#999999",
    }
    labels = {
        "Absolutt": "Totalt vandringshinder",
        "Partiell": "Delvis vandringshinder",
        "Nedstrøms hinder": "Hinder kun nedstrøms",
        "Ikke hinder": "Ikke et vandringshinder",
        "Neppe fiskeførende": "Neppe fiskeførende bekk",
        "Ikke angitt": "Ikke vurdert",
    }
    for cat in BARRIER_ORDER:
        rows += (
            f"<div style='margin:2px 0'>"
            f"<span style='display:inline-block;width:12px;height:12px;"
            f"border-radius:50%;background:{colors[cat]};margin-right:6px'></span>"
            f"{labels[cat]}</div>"
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


def main():
    df = load_data()
    has_height = "elevation_diff_m" in df.columns

    center_lat = df["lat_ned"].mean()
    center_lon = df["lon_ned"].mean()

    m = folium.Map(location=[center_lat, center_lon], zoom_start=9, tiles=None)
    add_base_layers(m)

    # One layer (FeatureGroup) per barrier category, so each can be
    # switched on/off independently in the layer control.
    groups = {cat: folium.FeatureGroup(name=f"Kulverter: {cat}") for cat in BARRIER_ORDER}
    line_group = folium.FeatureGroup(name="Linje nedstrøms->oppstrøms", show=False)

    for _, row in df.iterrows():
        cat = row.get("barrier_category", "Ikke angitt")
        group = groups.get(cat, groups["Ikke angitt"])

        folium.CircleMarker(
            location=[row["lat_ned"], row["lon_ned"]],
            radius=marker_radius(row, has_height),
            color=row.get("barrier_color", "#999999"),
            fill=True,
            fill_color=row.get("barrier_color", "#999999"),
            fill_opacity=0.85,
            weight=1,
            popup=folium.Popup(build_popup_html(row, has_height), max_width=300),
        ).add_to(group)

        if pd.notna(row.get("lat_opp")) and pd.notna(row.get("lon_opp")):
            folium.PolyLine(
                locations=[
                    [row["lat_ned"], row["lon_ned"]],
                    [row["lat_opp"], row["lon_opp"]],
                ],
                color=row.get("barrier_color", "#999999"),
                weight=2,
                opacity=0.7,
            ).add_to(line_group)

    for group in groups.values():
        group.add_to(m)
    line_group.add_to(m)

    add_legend(m)
    folium.LayerControl(collapsed=False).add_to(m)

    # Zoom to fit all the points instead of a fixed zoom level.
    bounds = [[df["lat_ned"].min(), df["lon_ned"].min()], [df["lat_ned"].max(), df["lon_ned"].max()]]
    m.fit_bounds(bounds)

    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(OUT_HTML))
    print(f"Saved map to {OUT_HTML}")
    print("Open this file in a web browser to view it.")


if __name__ == "__main__":
    main()
