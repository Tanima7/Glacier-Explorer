import ee
import datetime
import streamlit as st
import geemap.foliumap as geemap
from llm_core import (
    initialize_velocity_engine,
    render_manual_velocity_interface,
    render_ai_assistant_tab,
    add_velocity_to_map
)




# setting up the page configuaration
st.set_page_config(
    page_title="Glacier Explorer",
    page_icon="🧊",
    layout="wide"
)




# defining visualization palettes
VIS_PALETTES = {
    "Air Temperature": {
        'min': 250, 'max': 285,
        'palette': ['#313695', '#4575b4', '#74add1', '#abd9e9', '#e0f3f8', '#ffffbf', '#fee090', '#fdae61', '#f46d43', '#d73027', '#a50026']
    },
    "Rainfall Rate": {
        'min': 0, 'max': 0.001,
        'palette': ['#f7fbff', '#deebf7', '#c6dbef', '#9ecae1', '#6baed6', '#4292c6', '#2171b5', '#084594']
    },
    "Snowfall Rate": {
        'min': 0, 'max': 0.001,
        'palette': ['#f7f7f7', '#d9d9d9', '#bdbdbd', '#969696', '#737373', '#525252', '#252525']
    },
    "Snow Depth": {
        'min': 0, 'max': 5,
        'palette': ['#ffffd9', '#edf8b1', '#c7e9b4', '#7fcdbb', '#41b6c4', '#1d91c0', '#225ea8', '#0c2c84']
    },
    "Snow Water Content": {
        'min': 0, 'max': 500,
        'palette': ['#440154', '#414487', '#2a788e', '#22a884', '#7ad151', '#fde725']
    }
}




# creating a legend to understand the visualization
def create_floating_html_legend(vis_params, variable_name):
    """Generates a professional-looking floating HTML string for a map legend."""
    palette = vis_params.get('palette', [])
    min_val = vis_params.get('min', 0)
    max_val = vis_params.get('max', 1)




    # Calculating the middle value
    mid_val = (min_val + max_val) / 2

    unit_map = {"Temperature": "K", "Depth": "m", "Rate": "kg/m²/s", "Content": "kg/m²"}
    unit = next((u for k, u in unit_map.items() if k in variable_name), "")

    gradient_css = f"background: linear-gradient(to right, {', '.join(palette)});"

    legend_html = f"""
    <div style="
        position: fixed; 
        bottom: 50px; 
        left: 20px; 
        width: 250px; 
        background-color: rgba(255, 255, 255, 0.85);
        border-radius: 8px; 
        padding: 10px; 
        font-family: sans-serif;
        font-size: 14px;
        box-shadow: 0 2px 6px rgba(0,0,0,0.2);
        z-index: 1000;
        border: 1px solid #ddd;
        ">
        <div style="font-weight: bold; margin-bottom: 5px; color: #333;">{variable_name} ({unit})</div>
        <div style="height: 20px; border-radius: 4px; {gradient_css}"></div>
        <div style="display: flex; justify-content: space-between; font-size: 12px; margin-top: 4px; color: #555;">
            <span>{min_val:.1f}</span>
            <span style="text-align: center;">{mid_val:.1f}</span>
            <span>{max_val:.1f}</span>
        </div>
    </div>
    """
    return legend_html




# initializing
try:
    if not ee.data._credentials:
        ee.Authenticate()
    ee.Initialize(project="glacier-470302")
except Exception as e:
    st.error(f"Failed to initialize Google Earth Engine. Error: {e}")
    st.stop()

if 'velocity_engine' not in st.session_state:
    st.session_state.velocity_engine = initialize_velocity_engine()

st.title("🧊 Glacier Climate & Velocity Explorer")

# adding sidebar and containers
with st.sidebar:
    st.header("About")
    st.markdown("This interactive tool analyzes glacier climate and velocity using Google Earth Engine and Google's AI models.")
    st.divider()
    search_mode = st.radio("Select Location By:", ["Pre-defined Glaciers", "Custom Coordinates"], key="search_mode", horizontal=True)

with st.container(border=True):
    c1, c2, c3 = st.columns(3)
    location = {"lat": 30.32, "lon": 79.96, "zoom": 12}
    selected_glacier = "Pindari Glacier"
    with c1:
        if search_mode == "Custom Coordinates":
            st.subheader("📍 Custom Coordinates")
            lat = st.number_input("Latitude", value=30.32, min_value=-90.0, max_value=90.0, step=0.01)
            lon = st.number_input("Longitude", value=79.96, min_value=-180.0, max_value=180.0, step=0.01)
            location.update({"lat": lat, "lon": lon})
            selected_glacier = "Custom Location"
        else:
            st.subheader("🏔️ Pre-defined Glacier")
            glacier_locations = {
                "Pindari Glacier": {"lat": 30.32, "lon": 79.96, "zoom": 12},
                "Gangotri Glacier": {"lat": 30.93, "lon": 79.08, "zoom": 12},
                "Siachen Glacier": {"lat": 35.42, "lon": 77.10, "zoom": 11},
                "Baltoro Glacier": {"lat": 35.71, "lon": 76.43, "zoom": 11},
            }
            selected_glacier = st.selectbox("Select Glacier:", list(glacier_locations.keys()))
            location = glacier_locations[selected_glacier]
    with c2:
        st.subheader("🗓️ Analysis Date")
        date = st.date_input("Select a date for climate analysis", value=datetime.date(2023, 8, 15))
        st.caption("Note: Climate data is available up to 2023.")
    with c3:
        st.subheader("⚙️ Analysis Area")
        buffer_size = st.slider("Analysis Radius (km)", 1, 15, 5)
        zoom_level = st.slider("Map Zoom Level", 8, 15, location.get("zoom", 12))
        location["zoom"] = zoom_level





# fetching data 
try:
    center_point = ee.Geometry.Point([location["lon"], location["lat"]])
    analysis_area = center_point.buffer(buffer_size * 1000)
    glaciers_fc = ee.FeatureCollection("GLIMS/20230607").filterBounds(analysis_area)
    glacier_count = glaciers_fc.size().getInfo()
    glacier_info = {'name': selected_glacier, 'lat': location['lat'], 'lon': location['lon'], 'buffer_size': buffer_size, 'glacier_count': glacier_count}
    date_info = {'date': date.strftime("%Y-%m-%d")}
except Exception as e:
    st.error(f"An error occurred during Earth Engine processing: {e}")
    st.stop()




    

# interface
tab_map, tab_velocity, tab_ai = st.tabs(["🗺️ Climate Map", "🛰️ Velocity Analysis", "🤖 AI Assistant"])

with tab_map:
    map_col, controls_col = st.columns([4, 1])
    with controls_col:
        st.subheader("Map Layers")
        selected_climate_name = st.selectbox(
            "Climate Variable:",
            ["Air Temperature", "Rainfall Rate", "Snowfall Rate", "Snow Depth", "Snow Water Content"]
        )
        st.caption("Use the layer control on the map to toggle basemaps and data layers.")
        vis_params = VIS_PALETTES.get(selected_climate_name)

    with map_col:
        climate_map = {
            "Air Temperature": "Tair_f_tavg",
            "Rainfall Rate": "Rainf_f_tavg",
            "Snowfall Rate": "Snowf_tavg",
            "Snow Depth": "SnowDepth_inst",
            "Snow Water Content": "SWE_inst"
        }
        climate_var = climate_map[selected_climate_name]
        start_date_ee = ee.Date.fromYMD(date.year, date.month, 1)
        fldas = ee.ImageCollection("NASA/FLDAS/NOAH01/C/GL/M/V001").filterDate(start_date_ee, start_date_ee.advance(1, 'month')).select(climate_var)
        climate_img_unmasked = fldas.median().clip(analysis_area) if fldas.size().getInfo() > 0 else None
        climate_img = climate_img_unmasked.updateMask(ee.Image(0).paint(glaciers_fc, 1)) if climate_img_unmasked and glacier_count > 0 else climate_img_unmasked

        m = geemap.Map(center=[location["lat"], location["lon"]], zoom=location["zoom"], add_google_map=False)
        m.add_basemap("SATELLITE", visible=True)
        m.add_basemap("OpenStreetMap", visible=False)

        if climate_img:
            m.addLayer(climate_img, vis_params, f"{selected_climate_name}")
        
        if glacier_count > 0:
            glacier_style = {'color': '#00FFFF', 'fillColor': '#00FFFF', 'fillOpacity': 0.25, 'width': 2.0}
            m.addLayer(glaciers_fc, glacier_style, "Glacier Area")

        if 'velocity_result' in st.session_state and st.session_state.velocity_result.get('success'):
            add_velocity_to_map(m, st.session_state.velocity_result)

        map_title = f"{selected_climate_name} on {selected_glacier} ({date.strftime('%B %Y')})"
        st.subheader(map_title)
        
        st.markdown(create_floating_html_legend(vis_params, selected_climate_name), unsafe_allow_html=True)
        
        m.to_streamlit(height=600)

with tab_velocity:
    render_manual_velocity_interface(location, selected_glacier)

with tab_ai:
    climate_data = {'variable': climate_var, 'description': selected_climate_name, 'image_count': fldas.size().getInfo()}
    stats_data = climate_img.reduceRegion(reducer=ee.Reducer.mean().combine(ee.Reducer.minMax(), '', True), geometry=analysis_area, scale=1000, maxPixels=1e9).getInfo() if climate_img else None
    render_ai_assistant_tab(
        glacier_info=glacier_info,
        climate_data=climate_data,
        date_info=date_info,
        stats_data=stats_data,
        velocity_data=st.session_state.get('velocity_result')
    )