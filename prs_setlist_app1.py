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
TEMPLATE_FILENAME = "PRS SETLIST TEMPLATE.docx"
TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), TEMPLATE_FILENAME)

# --- 2. SEARCH LOGIC ---

def get_deezer_data(artist_name):
    """Attempt to get tracks automatically via Deezer API."""
    try:
        search = requests.get(f"https://api.deezer.com/search/artist?q={artist_name}", timeout=5).json()
        if search.get('data'):
            a_id = search['data'][0]['id']
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
    return None

def get_placeholder():
    """Default 25-minute live performance placeholder."""
    return [{"title": "LIVE PERFORMANCE / ORIGINAL MATERIAL", "duration": "25:00", "seconds": 1500}]

# --- 3. UI & APP LOGIC ---

st.set_page_config(page_title="PRS Toolkit Pro", layout="wide")
st.title("🎸 PRS Batch Setlist Generator")

if not os.path.exists(TEMPLATE_PATH):
    st.error(f"⚠️ Template file '{TEMPLATE_FILENAME}' not found. Please upload it to your GitHub repo.")

uploaded_file = st.file_uploader("Upload formatted_shows.csv", type="csv")

if uploaded_file:
    df = pd.read_csv(uploaded_file)
    
    # Store found songs in a session state so we don't re-search every time the UI updates
    if 'final_data' not in st.session_state:
        st.session_state.final_data = {}

    st.subheader("Step 1: Verify Artists")
    st.write("The app is searching for tracks. If an artist is flagged, provide a Spotify link or skip.")

    for idx, row in df.iterrows():
        artist = str(row['Artist']).strip()
        
        # If we haven't processed this artist yet, try auto-search
        if artist not in st.session_state.final_data:
            auto_songs = get_deezer_data(artist)
            if auto_songs:
                st.session_state.final_data[artist] = auto_songs
            else:
                st.session_state.final_data[artist] = "PENDING"

        # UI for Review
        with st.expander(f"Artist: {artist}", expanded=(st.session_state.final_data[artist] == "PENDING")):
            if st.session_state.final_data[artist] == "PENDING":
                st.warning(f"⚠️ No tracks found automatically for **{artist}**.")
                
                col1, col2 = st.columns([3, 1])
                with col1:
                    # Note: Pulling from a URL on Streamlit Cloud still requires the API or Scraper.
                    # For simplicity, we allow manual track entry or the placeholder.
                    spotify_url = st.text_input(f"Paste Spotify URL for {artist} (Optional)", key=f"url_{idx}")
                
                with col2:
                    if st.button(f"Use 25min Placeholder", key=f"btn_{idx}"):
                        st.session_state.final_data[artist] = get_placeholder()
                        st.rerun()
                
                # If they pasted a URL, for now we will suggest using placeholder 
                # unless you want to re-enable the Spotify API logic here.
                if spotify_url:
                    st.info("Direct URL scraping is restricted. Please use the placeholder or manually edit below.")

            else:
                st.success(f"✅ Setlist ready for {artist}")
                # Allow manual editing of the found tracks
                track_list = [s['title'] for s in st.session_state.final_data[artist]]
                new_tracks = st.text_area(f"Edit tracks for {artist} (one per line)", value="\n".join(track_list), key=f"edit_{idx}")
                
                # Update session state if edited
                if st.button(f"Save Edits for {artist}", key=f"save_{idx}"):
                    st.session_state.final_data[artist] = [{"title": t, "duration": "4:00", "seconds": 240} for t in new_tracks.split("\n") if t.strip()]

    # --- 4. GENERATION STEP ---
    st.divider()
    st.subheader("Step 2: Generate Files")
    
    if st.button("Generate All PRS Forms"):
        # Check if any are still pending
        if any(v == "PENDING" for v in st.session_state.final_data.values()):
            st.error("Please resolve all flagged artists (use placeholder or edit) before generating.")
        else:
            zip_buffer = BytesIO()
            with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
                progress = st.progress(0)
                
                for idx, row in df.iterrows():
                    artist = str(row['Artist']).strip()
                    songs = st.session_state.final_data.get(artist, get_placeholder())
                    
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
                    
                    try:
                        d_iso = datetime.strptime(str(row['Date']).strip(), "%d.%m.%Y").strftime("%Y-%m-%d")
                    except: d_iso = "0000-00-00"
                    
                    filename = f"{d_iso}_PRS_{artist.replace(' ', '_')}.docx"
                    doc_io = BytesIO()
                    doc.save(doc_io)
                    zip_file.writestr(filename, doc_io.getvalue())
                    progress.progress((idx + 1) / len(df))
                    
            st.success("Batch Complete!")
            st.download_button("📥 Download ZIP", zip_buffer.getvalue(), "PRS_Setlists.zip")