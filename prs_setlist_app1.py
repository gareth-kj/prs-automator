import streamlit as st
import pandas as pd
import requests
import json
import zipfile
import os
from ytmusicapi import YTMusic
from bs4 import BeautifulSoup
from io import BytesIO
from docxtpl import DocxTemplate

# Initialize YTMusic (No auth needed for public searches)
yt = YTMusic()

# --- 1. CORE UTILS ---
def dur_to_sec(dur_str):
    try:
        dur_str = str(dur_str).strip()
        if ":" in dur_str:
            m, s = map(int, dur_str.split(":"))
            return (m * 60) + s
        return int(float(dur_str)) * 60
    except: return 0

def sec_to_format(total_sec):
    return f"{total_sec // 60}m {total_sec % 60:02d}s"

# --- 2. THE NEW WATERFALL ENGINES ---

def get_yt_music_tracks(artist_name):
    """Stage 2: Fast, high-reliability metadata from YouTube Music."""
    try:
        # Search for the artist to get their BrowseID
        search_results = yt.search(artist_name, filter="artists")
        if not search_results: return None
        
        artist_id = search_results[0]['browseId']
        artist_data = yt.get_artist(artist_id)
        
        # Pull tracks from 'songs' or 'top tracks' section
        tracks = []
        # YTMusic usually returns 'songs' or 'singles'
        song_results = artist_data.get('songs', {}).get('results', [])
        
        for s in song_results[:10]:
            tracks.append({
                "Track Name": s['title'].upper(),
                "Length": s.get('duration', '04:00')
            })
        return tracks if tracks else None
    except: return None

def script_extract_spotify(url):
    """Stage 3: Direct extraction for manual URL overrides."""
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        scripts = soup.find_all('script', type='application/ld+json')
        songs = []
        for script in scripts:
            data = json.loads(script.string)
            if 'track' in data:
                for item in data['track']:
                    # Simple ISO 8601 duration parser (PT3M45S -> 3:45)
                    d = item.get('duration', '03:30').replace('PT','').replace('M',':').replace('S','')
                    songs.append({"Track Name": item.get('name').upper(), "Length": d})
        return songs[:10]
    except: return None

# --- 3. UI & BATCH LOGIC ---

st.set_page_config(page_title="PRS Pro Waterfall", layout="wide")
st.title("⚡ PRS Waterfall: Deezer + YT Music + Spotify")

if 'setlists' not in st.session_state:
    st.session_state.setlists = {}

uploaded_file = st.file_uploader("Upload CSV", type="csv")

if uploaded_file:
    df = pd.read_csv(uploaded_file)
    
    # 1. Start Automation Button
    if st.button("🚀 Run Full Waterfall Search"):
        for idx, row in df.iterrows():
            art = str(row['Artist']).strip()
            if art not in st.session_state.setlists or st.session_state.setlists[art].empty:
                with st.spinner(f"Processing {art}..."):
                    # Stage 1: Deezer
                    try:
                        r = requests.get(f"https://api.deezer.com/search/artist?q={art}", timeout=5).json()
                        a_id = r['data'][0]['id']
                        t = requests.get(f"https://api.deezer.com/artist/{a_id}/top?limit=10", timeout=5).json()
                        data = [{"Track Name": s['title'].upper(), "Length": f"{s['duration']//60}:{s['duration']%60:02d}"} for s in t['data']]
                    except: data = None
                    
                    # Stage 2: YT Music (The New Powerhouse)
                    if not data:
                        data = get_yt_music_tracks(art)
                    
                    st.session_state.setlists[art] = pd.DataFrame(data) if data else pd.DataFrame(columns=["Track Name", "Length"])
        st.rerun()

    # 2. Review & Manual Edit
    for idx, row in df.iterrows():
        art = str(row['Artist']).strip()
        if art not in st.session_state.setlists:
            st.session_state.setlists[art] = pd.DataFrame(columns=["Track Name", "Length"])
        
        with st.expander(f"{'✅' if not st.session_state.setlists[art].empty else '⚠️'} {art}"):
            # Manual URL Override
            c_url, c_btn = st.columns([3, 1])
            with c_url:
                m_url = st.text_input("Paste Spotify/YT Link", key=f"url_{art}")
            with c_btn:
                if st.button("Scrape Link", key=f"btn_{art}"):
                    res = script_extract_spotify(m_url)
                    if res: 
                        st.session_state.setlists[art] = pd.DataFrame(res)
                        st.rerun()

            # The Protected Table
            ed_df = st.data_editor(st.session_state.setlists[art], num_rows="dynamic", key=f"ed_{art}", use_container_width=True)
            st.session_state.setlists[art] = ed_df
            
            # Math
            total_s = sum(dur_to_sec(l) for l in st.session_state.setlists[art]["Length"])
            st.metric("Total Set Time", sec_to_format(total_s))

    # 3. Final ZIP Generation
    # (Existing DocxTemplate logic...)