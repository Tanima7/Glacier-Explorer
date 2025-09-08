import os
import google.generativeai as genai
from dotenv import load_dotenv
import streamlit as st
import ee
import datetime




# loading environment variables from a .env file
load_dotenv()

class GlacierQA:
    """Handles interaction with the Google AI API for Q&A."""
    def __init__(self):
        api_key = os.getenv('GOOGLE_API_KEY')
        if not api_key:
            raise ValueError("GOOGLE_API_KEY not found in .env file. Please set it.")
        
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-1.5-flash')
    
    def create_context(self, glacier_info, climate_data, date_info, stats_data=None, velocity_data=None):
        """Creates a detailed text context for the AI model based on the current analysis."""
        context = f"""
        **GLACIER ANALYSIS CONTEXT:**

        **Location Information:**
        - Glacier/Location: {glacier_info.get('name', 'Unknown')}
        - Coordinates: {glacier_info.get('lat', 'N/A'):.4f}°N, {glacier_info.get('lon', 'N/A'):.4f}°E
        - Analysis Date: {date_info.get('date', 'N/A')}

        **Climate Data (Source: FLDAS):**
        - Selected Variable: {climate_data.get('description', 'N/A')}
        """
        
        if stats_data:
            mean_temp_k = stats_data.get(f"{climate_data.get('variable')}_mean")
            if mean_temp_k and climate_data.get('variable') == 'Tair_f_tavg':
                mean_temp_c = mean_temp_k - 273.15
                context += f"- Mean Temperature: {mean_temp_k:.2f} K ({mean_temp_c:.2f} °C)\n"
            else:
                 context += f"- Mean Value: {stats_data.get(list(stats_data.keys())[0], 'N/A'):.4f}\n"

        if velocity_data:
            avg_vel = velocity_data.get('avg_velocity')
            max_vel = velocity_data.get('max_velocity')

            avg_vel_str = f"{avg_vel:.4f}" if isinstance(avg_vel, (int, float)) else "Not Calculated"
            max_vel_str = f"{max_vel:.4f}" if isinstance(max_vel, (int, float)) else "Not Calculated"

            context += f"""
        **Glacier Velocity Analysis (Source: Sentinel-2):**
        - Time Period: {velocity_data.get('date1', 'N/A')} to {velocity_data.get('date2', 'N/A')}
        - Average Velocity: {avg_vel_str} m/day
        - Max Velocity: {max_vel_str} m/day
        """
        
        context += """
        **Scientific Background:**
        - Glacier velocity often increases with temperature due to surface meltwater lubricating the glacier bed.
        - Summer velocities are typically higher than winter velocities.
        - Air temperature is a primary driver of glacier melt. A mean temperature above 0°C is significant.
        - Snowfall (accumulation) and melting (ablation) determine a glacier's mass balance and health.
        """
        return context
    
    def answer_question(self, question, context):
        """Sends the question and context to the Gemini model and returns the answer."""
        system_prompt = """
        You are an expert in glaciology and remote sensing. Your role is to analyze the provided data context and answer the user's question.
        - Be concise and clear.
        - Directly use the data from the context (e.g., temperature values, velocity).
        - Explain the scientific reasoning behind your answer.
        - If data is missing, state what is missing and how it would improve the analysis.
        - Keep your response to 2-3 paragraphs.
        """
        
        full_prompt = f"{system_prompt}\n\n{context}\n\n**User Question:** {question}"
        
        try:
            response = self.model.generate_content(full_prompt)
            return response.text
        except Exception as e:
            return f"Error generating response: {str(e)}"
    
    def suggest_questions(self, glacier_name, climate_variable, has_velocity=False):
        """Generates a list of relevant questions based on the current data."""
        questions = [
            f"How might current {climate_variable} conditions affect {glacier_name}?",
            f"What does this {climate_variable} data tell us about the glacier's health?",
        ]
        if has_velocity:
            questions.extend([
                "How does the measured velocity relate to the climate conditions?",
                "Is this velocity typical for a glacier in this region?",
            ])
        return questions

class GlacierVelocityEngine:
    """Handles all Google Earth Engine calculations for glacier velocity."""
    def __init__(self):
        self.max_offset_m = 100
        self.window_days = 30
        
    def _get_sentinel2_collection(self, aoi, start_date, end_date):
        """Helper to get a cloud-masked Sentinel-2 image collection."""
        def mask_s2_clouds(image):
            qa = image.select('QA60')
            cloud_bit_mask = 1 << 10
            cirrus_bit_mask = 1 << 11
            mask = qa.bitwiseAnd(cloud_bit_mask).eq(0).And(qa.bitwiseAnd(cirrus_bit_mask).eq(0))
            return image.updateMask(mask)

        return (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
                .filterBounds(aoi)
                .filterDate(start_date, end_date)
                .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 20))
                .map(mask_s2_clouds))
    
    def calculate_velocity(self, lat, lon, date1, date2, buffer_km):
        """Calculates glacier velocity between two dates using feature tracking."""
        try:
            point = ee.Geometry.Point([lon, lat])
            aoi = point.buffer(buffer_km * 1000)
            
            dt1 = datetime.datetime.strptime(date1, "%Y-%m-%d")
            dt2 = datetime.datetime.strptime(date2, "%Y-%m-%d")
            
            col1 = self._get_sentinel2_collection(aoi, (dt1 - datetime.timedelta(days=self.window_days)).strftime("%Y-%m-%d"), (dt1 + datetime.timedelta(days=self.window_days)).strftime("%Y-%m-%d"))
            col2 = self._get_sentinel2_collection(aoi, (dt2 - datetime.timedelta(days=self.window_days)).strftime("%Y-%m-%d"), (dt2 + datetime.timedelta(days=self.window_days)).strftime("%Y-%m-%d"))

            if col1.size().getInfo() == 0 or col2.size().getInfo() == 0:
                return {'success': False, 'error': f'Insufficient cloud-free images found. Period 1 had {col1.size().getInfo()} images, Period 2 had {col2.size().getInfo()}. Try different dates.'}

            img1 = col1.sort('CLOUDY_PIXEL_PERCENTAGE').first()
            img2 = col2.sort('CLOUDY_PIXEL_PERCENTAGE').first()
            
            displacement = img2.select('B8').displacement(referenceImage=img1.select('B8'), maxOffset=self.max_offset_m, patchWidth=256)
            dx = displacement.select('dx')
            dy = displacement.select('dy')
            
            time_gap_days = abs((dt2 - dt1).days)
            if time_gap_days == 0: time_gap_days = 1
            
            speed_m_day = dx.hypot(dy).divide(time_gap_days).rename('velocity')
            
            glaciers = ee.FeatureCollection("GLIMS/20230607").filterBounds(aoi)
            if glaciers.size().getInfo() == 0:
                 return {'success': False, 'error': 'No GLIMS glacier polygons found in the analysis area.'}
            glacier_mask = ee.Image(0).paint(glaciers, 1).gt(0)
            speed_final = speed_m_day.updateMask(glacier_mask)
            
            stats = speed_final.reduceRegion(reducer=ee.Reducer.mean().combine(ee.Reducer.minMax(), '', True), geometry=aoi, scale=100, maxPixels=1e9).getInfo()
            
            return {
                'success': True, 'velocity_m_day': speed_final, 'glacier_polygons': glaciers,
                'time_gap_days': time_gap_days, 'stats': stats, 'analysis_dates': (date1, date2)
            }
        except Exception as e:
            return {'success': False, 'error': f'Velocity calculation failed: {str(e)}'}

def initialize_velocity_engine():
    """Initializes the velocity engine with error handling."""
    try:
        return GlacierVelocityEngine()
    except Exception as e:
        st.error(f"Failed to initialize velocity engine: {e}")
        return None

def add_velocity_to_map(m, velocity_result):
    """Adds velocity raster layers to an existing geemap Map object."""
    if not velocity_result or not velocity_result.get('success'):
        return
    
    speed_vis = {'min': 0, 'max': 2.0, 'palette': ['blue', 'cyan', 'yellow', 'red']}
    m.addLayer(velocity_result['velocity_m_day'], speed_vis, "Glacier Velocity (m/day)")

def render_manual_velocity_interface(location, selected_glacier):
    """Renders the UI for manual velocity analysis."""
    st.subheader("Glacier Velocity Analysis")
    st.info("Measure glacier speed between two dates using Sentinel-2 satellite imagery.")

    col1, col2, col3 = st.columns([1, 1, 1])
    date1 = col1.date_input("Start Date", value=datetime.date(2023, 6, 1))
    date2 = col2.date_input("End Date", value=datetime.date(2023, 8, 31))
    
    if col3.button("Calculate Velocity", type="primary", use_container_width=True):
        if date1 >= date2:
            st.error("End date must be after start date.")
        else:
            engine = st.session_state.velocity_engine
            with st.spinner("Calculating velocity... This can take up to a minute."):
                result = engine.calculate_velocity(location['lat'], location['lon'], date1.strftime("%Y-%m-%d"), date2.strftime("%Y-%m-%d"), 5)
                st.session_state.velocity_result = result
            st.rerun()

    if 'velocity_result' in st.session_state:
        result = st.session_state.velocity_result
        if result.get('success'):
            stats = result.get('stats', {})
            mean_vel = stats.get('velocity_mean', 0) or 0
            max_vel = stats.get('velocity_max', 0) or 0
            st.success(f"Analysis Complete for **{result['time_gap_days']} days**.")
            c1, c2, c3 = st.columns(3)
            c1.metric("Avg. Velocity", f"{mean_vel:.2f} m/day")
            c2.metric("Max. Velocity", f"{max_vel:.2f} m/day")
            c3.metric("Est. Annual Speed", f"{mean_vel * 365.25:.1f} m/year")
        else:
            st.error(f"Analysis Failed: {result.get('error', 'Unknown error')}")

def render_ai_assistant_tab(glacier_info, climate_data, date_info, stats_data=None, velocity_data=None):
    """Renders the entire Q&A tab, including input, suggestions, and output."""
    st.subheader("Ask the AI Glacier Expert")
    
    if 'qa_system' not in st.session_state:
        st.session_state.qa_system = GlacierQA()
    qa_system = st.session_state.qa_system

    def update_question_text(suggestion):
        st.session_state.qa_question_input = suggestion

    col1, col2 = st.columns([3, 2])
    with col1:
        question = st.text_area("Your Question:", key="qa_question_input", placeholder="e.g., How does the temperature affect the glacier's movement?", height=120)
        if st.button("Get Expert Answer", type="primary"):
            if question.strip():
                with st.spinner("AI is analyzing your data..."):
                    context = qa_system.create_context(glacier_info, climate_data, date_info, stats_data, velocity_data)
                    answer = qa_system.answer_question(question, context)
                    st.session_state.qa_latest_question = question
                    st.session_state.qa_latest_answer = answer
            else:
                st.warning("Please enter a question.")
    
    with col2:
        st.write("**Suggested Questions:**")
        has_velocity = velocity_data is not None
        suggestions = qa_system.suggest_questions(glacier_info.get('name', 'this glacier'), climate_data.get('description', 'climate data'), has_velocity)
        for i, suggestion in enumerate(suggestions):
            st.button(suggestion, key=f"suggestion_{i}", on_click=update_question_text, args=(suggestion,), use_container_width=True)

    if 'qa_latest_answer' in st.session_state:
        st.markdown("---")
        with st.container(border=True):
            st.info(f"**Your Question:** {st.session_state.qa_latest_question}")
            st.markdown(st.session_state.qa_latest_answer)
            answer_text = f"Question: {st.session_state.qa_latest_question}\n\nAnswer:\n{st.session_state.qa_latest_answer}"
            st.download_button("Download Answer", answer_text, file_name="glacier_analysis.txt", key="download_answer_button")

def render_complete_glacier_interface(location, selected_glacier, glacier_info, climate_data, date_info, stats_data):
    """Creates the main tabbed interface for Velocity and AI analysis."""
    velocity_data = None
    if 'velocity_result' in st.session_state and st.session_state.velocity_result.get('success'):
        result = st.session_state.velocity_result
        stats = result.get('stats', {})
        velocity_data = {
            'date1': result.get('analysis_dates', ('N/A',))[0],
            'date2': result.get('analysis_dates', ('N/A', 'N/A'))[1],
            'time_gap_days': result.get('time_gap_days', 0),
            'avg_velocity': stats.get('velocity_mean', 0) or 0,
            'max_velocity': stats.get('velocity_max', 0) or 0,
        }

    tab1, tab2 = st.tabs(["Velocity Analysis", "AI Assistant"])
    
    with tab1:
        render_manual_velocity_interface(location, selected_glacier)
        
    with tab2:
        render_ai_assistant_tab(glacier_info, climate_data, date_info, stats_data, velocity_data)