import streamlit as st
import pandas as pd
import requests
import zipfile
import os
import re
import time
from datetime import datetime
from io import BytesIO
from docxtpl import DocxTemplate

# --- 1. CONFIGURATION ---
VENUES = {
    "The Social": {"address": "5 Little Portland Street, London, W1W 7JD", "tel": "020 7636 4992", "position": "Venue Manager"},
    "The Windmill Brixton": {"address": "22 Blenheim Gardens, London, SW2 5BZ", "tel": "020 8671 0700", "position": "Promoter"}
}
TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "PRS SETLIST TEMPLATE.docx")

# --- 2. THE RELIABLE WATERFALL (No Selenium required for Stage 1) ---

def get_deezer_data(artist_name):
    """Stage 1: Deezer API (Reliable, fast, no bot blocking)."""
    try:
        # Search for artist
        search = requests.get(f"https://api.deezer.com/search/artist?q={artist_name}", timeout=5).json()
        if search.get('data'):
            a_id = search['data'][0]['id']
            # Get their top 10 tracks
            tracks = requests.get(f"https://api.deezer.com/artist/{a_id}/top?limit=10", timeout=5).json()
            if tracks.get('data'):
                return [
                    {
                        "title": t['title'], 
                        "duration": f"{int(t['duration'])//60}:{int(t['duration'])%60:02d}", 
                        "seconds": int(t['duration'])
                    } for t in tracks['data']
                ]
    except: pass
    return []

def get_bandcamp_data(artist_name):
    """Stage 2: Bandcamp Search (Fallback)."""
    try:
        # Bandcamp search is more open to simple requests than Spotify
        headers = {'User-Agent': 'Mozilla/5.0'}
        url = f"https://bandcamp.com/search?q={artist_name.replace(' ', '%20')}"
        # This is a simplified logic - in a real scenario, we'd use a light scraper here
        # For now, we return empty to trigger the manual entry if Deezer fails
    except: pass
    return []

def get_songs_waterfall(artist_name):
    st.info(f"🔍 Fetching tracks for: **{artist_name}**")
    
    # Priority 1: Deezer (The 'Cardboard' & 'Last Apollo' Fix)
    songs = get_deezer_data(artist_name)
    if songs: 
        st.success(f"✅ Found tracks on Deezer")
        return songs
    
    st.warning(f"⚠️ Could not find tracks for {artist_name}. Using placeholder.")
    return [{"title": "LIVE PERFORMANCE / UNRELEASED", "duration": "4:00", "seconds": 240}]

# --- 3. THE APP INTERFACE ---

st.set_page_config(page_title="PRS Toolkit Pro", layout="wide")
st.title("🎸 PRS Batch Setlist Generator")

# Check for template
if not os.path.exists(TEMPLATE_PATH):
    st.error("⚠️ Template file 'PRS SETLIST TEMPLATE.docx' not found in folder.")

uploaded_file = st.file_uploader("Upload formatted_shows.csv", type="csv")

if uploaded_file:
    df = pd.read_csv(uploaded_file)
    
    # Let user preview and edit the data before generating
    st.subheader("Preview Data")
    edited_df = st.data_editor(df, num_rows="dynamic")

    if st.button("Generate All PRS Forms"):
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
            progress = st.progress(0)
            
            for idx, row in edited_df.iterrows():
                artist = str(row['Artist']).strip()
                songs = get_songs_waterfall(artist)
                
                # Venue/Promoter Info
                v_name = row.get('Venue Name', 'The Social')
                v_info = VENUES.get(v_name, VENUES["The Social"])
                total_sec = sum(s['seconds'] for s in songs)
                
                context = {
                    'V_NAME': v_name, 
                    'V_ADDR': row.get('Venue Address', v_info['address']),
                    'V_TEL': v_info['tel'], 
                    'DATE': row['Date'], 
                    'ARTIST': artist,
                    'P_NAME': row.get('Promoter Name', ''), 
                    'P_EMAIL': row.get('Promoter Email', ''),
                    'TOTAL_DURATION': f"{total_sec // 60}m {total_sec % 60:02d}s"
                }
                
                doc = DocxTemplate(TEMPLATE_PATH)
                doc.render(context)
                
                # Fill Table
                table = doc.tables[-1]
                for i, s in enumerate(songs[:10]):
                    try:
                        table.cell(i+1, 1).text = s['title'].upper()
                        table.cell(i+1, 4).text = s['duration']
                    except: break
                
                # Filename: YYYY-MM-DD_PRS_Artist.docx
                try:
                    d_iso = datetime.strptime(str(row['Date']).strip(), "%d.%m.%Y").strftime("%Y-%m-%d")
                except: d_iso = "0000-00-00"
                
                filename = f"{d_iso}_PRS_{artist.replace(' ', '_')}.docx"
                doc_io = BytesIO()
                doc.save(doc_io)
                zip_file.writestr(filename, doc_io.getvalue())
                
                progress.progress((idx + 1) / len(edited_df))
                
        st.success("Documents Created Successfully!")
        st.download_button("📥 Download ZIP", zip_buffer.getvalue(), "PRS_Setlists.zip")