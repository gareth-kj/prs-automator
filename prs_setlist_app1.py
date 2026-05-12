import streamlit as st
import pandas as pd
import requests
import zipfile
import os
import time
from datetime import datetime
from io import BytesIO
from docxtpl import DocxTemplate

# --- 1. MATH HELPERS ---

def duration_to_seconds(dur_str):
    """Converts MM:SS or M:SS to total seconds for summation."""
    try:
        dur_str = str(dur_str).strip()
        if ":" in dur_str:
            parts = dur_str.split(":")
            # Handle cases like "04:30" or "4:30"
            m = int(parts[0])
            s = int(parts[1])
            return (m * 60) + s
        # Fallback if user just types a number (assume minutes)
        return int(float(dur_str)) * 60
    except:
        return 0

def format_seconds(total_sec):
    """Formats total seconds to 'XXm YYs'."""
    mins = total_sec // 60
    secs = total_sec % 60
    return f"{mins}m {secs:02d}s"

# --- 2. CONFIGURATION ---
VENUES = {
    "The Social": {"address": "5 Little Portland Street, London, W1W 7JD", "tel": "020 7636 4992", "position": "Venue Manager"},
    "The Windmill Brixton": {"address": "22 Blenheim Gardens, London, SW2 5BZ", "tel": "020 8671 0700", "position": "Promoter"}
}
TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "PRS SETLIST TEMPLATE.docx")

# --- 3. THE APP UI ---

st.set_page_config(page_title="PRS Toolkit Pro", layout="wide")
st.title("🎸 PRS Batch Setlist Generator")

uploaded_file = st.file_uploader("Upload formatted_shows.csv", type="csv")

if uploaded_file:
    df = pd.read_csv(uploaded_file)
    
    # Initialize the session state for setlists as DataFrames
    if 'setlists' not in st.session_state:
        st.session_state.setlists = {}

    st.subheader("Step 1: Setlist Verification")

    for idx, row in df.iterrows():
        artist = str(row['Artist']).strip()
        
        # If artist not processed, initialize an empty 2-column DataFrame
        if artist not in st.session_state.setlists:
            st.session_state.setlists[artist] = pd.DataFrame(
                [{"Track Name": "", "Length": "03:30"}], # Start with one empty row
                columns=["Track Name", "Length"]
            )

        with st.expander(f"Artist: {artist}"):
            col1, col2 = st.columns([3, 1])
            
            with col1:
                # DUAL COLUMN DATA EDITOR
                # We use a unique key and disable automatic assumption of values
                edited_df = st.data_editor(
                    st.session_state.setlists[artist],
                    column_config={
                        "Track Name": st.column_config.TextColumn("Track Name", width="large", placeholder="e.g. Song Title"),
                        "Length": st.column_config.TextColumn("Length (MM:SS)", width="small", placeholder="03:30")
                    },
                    num_rows="dynamic",
                    key=f"editor_{artist}_{idx}"
                )
                # Update the state immediately
                st.session_state.setlists[artist] = edited_df

            with col2:
                st.write("**Controls**")
                
                # Placeholder Button
                if st.button(f"⚡ 25m Placeholder", key=f"pl_{idx}"):
                    st.session_state.setlists[artist] = pd.DataFrame([
                        {"Track Name": "LIVE PERFORMANCE / ORIGINAL MATERIAL", "Length": "25:00"}
                    ])
                    st.rerun()

                # Running Total Calculation
                current_df = st.session_state.setlists[artist]
                total_seconds = sum(duration_to_seconds(ln) for ln in current_df["Length"] if pd.notnull(ln))
                st.metric("Total Set Time", format_seconds(total_seconds))

    # --- 4. BATCH GENERATION ---
    st.divider()
    if st.button("🚀 Generate All PRS Forms", type="primary"):
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_f:
            for _, row in df.iterrows():
                art = str(row['Artist']).strip()
                songs_df = st.session_state.setlists.get(art)
                
                # Math for the Final PDF/Word Sum
                total_sec = sum(duration_to_seconds(ln) for ln in songs_df["Length"] if pd.notnull(ln))
                
                v_info = VENUES.get(row.get('Venue Name', 'The Social'), VENUES["The Social"])
                
                context = {
                    'V_NAME': row.get('Venue Name', 'The Social'),
                    'V_ADDR': row.get('Venue Address', v_info['address']),
                    'V_TEL': v_info['tel'], 
                    'DATE': row['Date'], 
                    'ARTIST': art,
                    'TOTAL_DURATION': format_seconds(total_sec)
                }
                
                doc = DocxTemplate(TEMPLATE_PATH)
                doc.render(context)
                
                # Populate the Word Table
                table = doc.tables[-1]
                for i, (_, s_row) in enumerate(songs_df.iterrows()):
                    if i >= 10: break # Standard template limit
                    try:
                        table.cell(i+1, 1).text = str(s_row["Track Name"]).upper()
                        table.cell(i+1, 4).text = str(s_row["Length"])
                    except: break
                
                # Filename logic
                try:
                    d_iso = datetime.strptime(str(row['Date']).strip(), "%d.%m.%Y").strftime("%Y-%m-%d")
                except: d_iso = "0000-00-00"
                
                filename = f"{d_iso}_PRS_{art.replace(' ', '_')}.docx"
                doc_io = BytesIO()
                doc.save(doc_io)
                zip_f.writestr(filename, doc_io.getvalue())
        
        st.success("Documents ready with calculated totals.")
        st.download_button("📥 Download ZIP", zip_buffer.getvalue(), "PRS_Setlists.zip")