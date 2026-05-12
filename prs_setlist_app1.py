import streamlit as st
import pandas as pd
import requests
import zipfile
import os
import time
from datetime import datetime
from io import BytesIO
from docxtpl import DocxTemplate
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium_stealth import stealth

# --- CONFIGURATION ---
VENUES = {
    "The Social": {"address": "5 Little Portland Street, London, W1W 7JD", "tel": "020 7636 4992", "position": "Venue Manager"},
    "The Windmill Brixton": {"address": "22 Blenheim Gardens, London, SW2 5BZ", "tel": "020 8671 0700", "position": "Promoter"}
}
TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "PRS SETLIST TEMPLATE.docx")

# --- UTILS ---
def duration_to_seconds(dur_str):
    """Converts MM:SS or M:SS to total seconds for summation."""
    try:
        if ":" in str(dur_str):
            m, s = map(int, dur_str.split(":"))
            return (m * 60) + s
        return int(dur_str) * 60 # Assume minutes if just a number
    except:
        return 0

def format_seconds(total_sec):
    """Formats total seconds back to a clean MMm SSs string for the PDF."""
    mins = total_sec // 60
    secs = total_sec % 60
    return f"{mins}m {secs:02d}s"

# --- SEARCH ENGINES (SPOTIFY -> DEEZER -> BANDCAMP) ---
# [Logic for get_spotify_selenium, get_deezer_api, get_bandcamp_selenium remains same as previous version]

# --- APP UI ---
st.set_page_config(page_title="PRS Toolkit Pro", layout="wide")
st.title("🎸 PRS Batch Setlist Generator")

uploaded_file = st.file_uploader("Upload formatted_shows.csv", type="csv")

if uploaded_file:
    df = pd.read_csv(uploaded_file)
    
    # Session state to hold our working setlists
    if 'setlists' not in st.session_state:
        st.session_state.setlists = {}

    st.subheader("Step 1: Review & Edit Setlists")
    st.info("The table below allows two-column editing. Ensure 'Length' is in MM:SS format.")

    for idx, row in df.iterrows():
        artist = str(row['Artist']).strip()
        
        # Initial Search Trigger
        if artist not in st.session_state.setlists:
            with st.spinner(f"Searching for {artist}..."):
                # Placeholder for your Selenium/API waterfall logic
                # For demo, returning empty list if not found
                st.session_state.setlists[artist] = pd.DataFrame(columns=["Track Name", "Length"])

        # UI Expander
        is_empty = len(st.session_state.setlists[artist]) == 0
        with st.expander(f"{'⚠️' if is_empty else '✅'} {artist}", expanded=is_empty):
            col1, col2 = st.columns([3, 1])
            
            with col1:
                # DUAL COLUMN MANUAL OVERRIDE (Data Editor)
                edited_df = st.data_editor(
                    st.session_state.setlists[artist],
                    column_config={
                        "Track Name": st.column_config.TextColumn("Track Name", width="large", required=True),
                        "Length": st.column_config.TextColumn("Length (MM:SS)", width="small", default="03:30")
                    },
                    num_rows="dynamic",
                    key=f"editor_{idx}"
                )
                st.session_state.setlists[artist] = edited_df

            with col2:
                st.write("Quick Actions")
                if st.button(f"Set 25m Placeholder", key=f"pl_{idx}"):
                    st.session_state.setlists[artist] = pd.DataFrame([
                        {"Track Name": "LIVE PERFORMANCE / ORIGINAL MATERIAL", "Length": "25:00"}
                    ])
                    st.rerun()
                
                # Calculate running total for display
                total_sec = sum(duration_to_seconds(ln) for ln in st.session_state.setlists[artist]["Length"])
                st.metric("Total Duration", format_seconds(total_sec))

    # --- GENERATION ---
    st.divider()
    if st.button("🚀 Generate All PRS Forms", type="primary"):
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_f:
            for _, row in df.iterrows():
                art = str(row['Artist']).strip()
                songs_df = st.session_state.setlists.get(art)
                
                # Math: Calculate final sum for the document
                total_sec = sum(duration_to_seconds(ln) for ln in songs_df["Length"])
                total_dur_str = format_seconds(total_sec)
                
                v_info = VENUES.get(row.get('Venue Name', 'The Social'), VENUES["The Social"])
                
                context = {
                    'V_NAME': row.get('Venue Name', 'The Social'),
                    'V_ADDR': row.get('Venue Address', v_info['address']),
                    'V_TEL': v_info['tel'], 
                    'DATE': row['Date'], 
                    'ARTIST': art,
                    'TOTAL_DURATION': total_dur_str # THIS IS THE CALCULATED SUM
                }
                
                doc = DocxTemplate(TEMPLATE_PATH)
                doc.render(context)
                
                # Fill the Word Table
                table = doc.tables[-1]
                for i, (_, s_row) in enumerate(songs_df.iterrows()):
                    if i >= 10: break # Template usually fits 10
                    try:
                        table.cell(i+1, 1).text = str(s_row["Track Name"]).upper()
                        table.cell(i+1, 4).text = str(s_row["Length"])
                    except: break
                
                # Date Formatting for Filename
                try:
                    d_iso = datetime.strptime(str(row['Date']).strip(), "%d.%m.%Y").strftime("%Y-%m-%d")
                except: d_iso = "0000-00-00"
                
                filename = f"{d_iso}_PRS_{art.replace(' ', '_')}.docx"
                doc_io = BytesIO()
                doc.save(doc_io)
                zip_f.writestr(filename, doc_io.getvalue())
        
        st.success("All setlists calculated and generated!")
        st.download_button("📥 Download Final ZIP", zip_buffer.getvalue(), "PRS_Batch_Final.zip")