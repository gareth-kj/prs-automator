import streamlit as st
import pandas as pd
import requests
import json
import zipfile
import os
import time
import subprocess
from datetime import datetime
from io import BytesIO
from docxtpl import DocxTemplate

# 1. Playwright Setup (Force check only when needed to save memory)
def get_playwright():
    try:
        from playwright.sync_api import sync_playwright
        from playwright_stealth import Stealth
        return sync_playwright, Stealth
    except ImportError:
        subprocess.run(["playwright", "install", "chromium"])
        from playwright.sync_api import sync_playwright
        from playwright_stealth import Stealth
        return sync_playwright, Stealth

# 2. YTMusic Setup
try:
    from ytmusicapi import YTMusic
    yt = YTMusic()
except:
    yt = None

# --- CORE UTILS ---
def dur_to_sec(dur_str):
    try:
        if ":" in str(dur_str):
            m, s = map(int, str(dur_str).split(":"))
            return (m * 60) + s
        return 0
    except: return 0

def sec_to_format(total_sec):
    return f"{total_sec // 60}m {total_sec % 60:02d}s"

# --- SCRAPER ---
def stage_3_playwright_scrape(url):
    try:
        sync_p, Stealth = get_playwright()
        with sync_p() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            Stealth().apply(page)
            page.goto(url, wait_until="networkidle", timeout=20000)
            time.sleep(2)
            
            tracks = []
            rows = page.query_selector_all('div[role="row"], .track_row_view, [data-testid="tracklist-row"]')
            for row in rows[:10]:
                try:
                    text = row.inner_text().split('\n')
                    clean = [t for t in text if len(t) > 1]
                    name = clean[1] if len(clean) > 1 else clean[0]
                    dur = next((t for t in clean if ":" in t and len(t) <= 5), "03:30")
                    tracks.append({"Track Name": name.upper(), "Length": dur})
                except: continue
            browser.close()
            return tracks
    except Exception as e:
        st.error(f"Scrape Error: {e}")
        return None

# --- UI LOGIC ---
st.set_page_config(page_title="PRS Waterfall Pro", layout="wide")
st.title("🎸 PRS Batch Setlist Generator")

if 'setlists' not in st.session_state:
    st.session_state.setlists = {}

uploaded_file = st.file_uploader("Upload formatted_shows.csv", type="csv")

if uploaded_file:
    df = pd.read_csv(uploaded_file)
    
    # NEW: Status UI
    st.info(f"Loaded {len(df)} artists from CSV.")
    
    # STABILIZED LOOP
    if st.button("🚀 Run Automated Search"):
        progress_text = st.empty()
        bar = st.progress(0)
        
        for i, row in df.iterrows():
            art = str(row['Artist']).strip()
            progress_text.text(f"Processing ({i+1}/{len(df)}): {art}")
            
            # Only search if table is currently empty
            if art not in st.session_state.setlists or st.session_state.setlists[art].empty:
                # Stage 1: Deezer
                data = None
                try:
                    r = requests.get(f"https://api.deezer.com/search/artist?q={art}", timeout=5).json()
                    a_id = r['data'][0]['id']
                    t = requests.get(f"https://api.deezer.com/artist/{a_id}/top?limit=10", timeout=5).json()
                    data = [{"Track Name": s['title'].upper(), "Length": f"{s['duration']//60}:{s['duration']%60:02d}"} for s in t['data']]
                except: pass
                
                # Stage 2: YT Music
                if not data and yt:
                    try:
                        s = yt.search(art, filter="artists")[0]
                        songs = yt.get_artist(s['browseId'])['songs']['results']
                        data = [{"Track Name": sg['title'].upper(), "Length": sg.get('duration', '03:45')} for sg in songs[:10]]
                    except: pass
                
                st.session_state.setlists[art] = pd.DataFrame(data) if data else pd.DataFrame(columns=["Track Name", "Length"])
            
            bar.progress((i + 1) / len(df))
        
        progress_text.success("Search Complete!")
        time.sleep(1)
        st.rerun()

    # --- THE REVIEW LIST ---
    for idx, row in df.iterrows():
        art = str(row['Artist']).strip()
        if art not in st.session_state.setlists:
            st.session_state.setlists[art] = pd.DataFrame(columns=["Track Name", "Length"])
        
        with st.expander(f"{'✅' if not st.session_state.setlists[art].empty else '⚠️'} Artist: {art}"):
            c_u, c_b = st.columns([3, 1])
            with c_u:
                m_url = st.text_input("Manual URL Override", key=f"url_{art}_{idx}")
            with c_b:
                if st.button("Scrape Link", key=f"btn_{art}_{idx}"):
                    with st.spinner("Scraping..."):
                        res = stage_3_playwright_scrape(m_url)
                        if res:
                            st.session_state.setlists[art] = pd.DataFrame(res)
                            st.rerun()

            st.session_state.setlists[art] = st.data_editor(
                st.session_state.setlists[art],
                num_rows="dynamic",
                key=f"ed_{art}_{idx}",
                use_container_width=True
            )
            
            total_s = sum(dur_to_sec(l) for l in st.session_state.setlists[art]["Length"] if pd.notnull(l))
            st.metric("Total Set Time", sec_to_format(total_s))

    # --- ZIP EXPORT (Simplified & Robust) ---
    st.divider()
    if st.button("🚀 Generate Final PRS ZIP", type="primary"):
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_f:
            for _, row in df.iterrows():
                art = str(row['Artist']).strip()
                s_df = st.session_state.setlists.get(art, pd.DataFrame())
                total_s = sum(dur_to_sec(l) for l in s_df["Length"] if pd.notnull(l))
                
                # Context mapping...
                # (Remaining DocxTemplate code is same as previous version)
                pass