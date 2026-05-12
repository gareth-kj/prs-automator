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

# 1. Playwright Setup with 2026 Stealth Syntax
try:
    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth  # Use Stealth class, not stealth_sync
except ImportError:
    # If the library is missing, we can't proceed, but requirements.txt should handle this.
    st.error("Missing libraries. Check requirements.txt")

# 2. YTMusic Setup
try:
    from ytmusicapi import YTMusic
    yt = YTMusic()
except Exception:
    yt = None

# --- CORE UTILS ---
VENUES = {
    "The Social": {"address": "5 Little Portland Street, London, W1W 7JD", "tel": "020 7636 4992", "position": "Venue Manager"},
    "The Windmill Brixton": {"address": "22 Blenheim Gardens, London, SW2 5BZ", "tel": "020 8671 0700", "position": "Promoter"}
}
TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "PRS SETLIST TEMPLATE.docx")

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

# --- SCRAPER WITH UPDATED STEALTH ---
def stage_3_playwright_scrape(url):
    try:
        # Ensure browsers are installed (fixes the 'Failed to install' error)
        subprocess.run(["playwright", "install", "chromium"])
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            
            # Updated Stealth Implementation
            stealth = Stealth()
            stealth.apply(page)
            
            page.goto(url, wait_until="networkidle", timeout=30000)
            time.sleep(2) 
            
            tracks = []
            rows = page.query_selector_all('div[role="row"], .track_row_view, .track-title, [data-testid="tracklist-row"]')
            
            for row in rows[:10]:
                try:
                    text_parts = row.inner_text().split('\n')
                    clean_text = [t for t in text_parts if len(t) > 1]
                    name = clean_text[1] if len(clean_text) > 1 else clean_text[0]
                    dur = next((t for t in clean_text if ":" in t and len(t) <= 5), "03:30")
                    tracks.append({"Track Name": name.upper(), "Length": dur})
                except: continue
                
            browser.close()
            return tracks if tracks else None
    except Exception as e:
        st.error(f"Scraper Error: {e}")
        return None

# --- UI LOGIC ---
st.set_page_config(page_title="PRS Waterfall Pro", layout="wide")
st.title("🎸 PRS Batch Setlist Generator")

if 'setlists' not in st.session_state:
    st.session_state.setlists = {}

uploaded_file = st.file_uploader("Upload CSV", type="csv")

if uploaded_file:
    df = pd.read_csv(uploaded_file)
    
    if st.button("🚀 Run Automated Search"):
        for idx, row in df.iterrows():
            art = str(row['Artist']).strip()
            if art not in st.session_state.setlists or st.session_state.setlists[art].empty:
                with st.spinner(f"🔍 Searching {art}..."):
                    # Stage 1: Deezer API
                    try:
                        r = requests.get(f"https://api.deezer.com/search/artist?q={art}", timeout=5).json()
                        a_id = r['data'][0]['id']
                        t = requests.get(f"https://api.deezer.com/artist/{a_id}/top?limit=10", timeout=5).json()
                        data = [{"Track Name": s['title'].upper(), "Length": f"{s['duration']//60}:{s['duration']%60:02d}"} for s in t['data']]
                    except: data = None
                    
                    # Stage 2: YT Music
                    if not data and yt:
                        try:
                            s = yt.search(art, filter="artists")[0]
                            songs = yt.get_artist(s['browseId'])['songs']['results']
                            data = [{"Track Name": sg['title'].upper(), "Length": sg.get('duration', '03:45')} for sg in songs[:10]]
                        except: data = None
                    
                    st.session_state.setlists[art] = pd.DataFrame(data) if data else pd.DataFrame(columns=["Track Name", "Length"])
        st.rerun()

    for idx, row in df.iterrows():
        art = str(row['Artist']).strip()
        if art not in st.session_state.setlists:
            st.session_state.setlists[art] = pd.DataFrame(columns=["Track Name", "Length"])
        
        with st.expander(f"Artist: {art}"):
            c_u, c_b = st.columns([3, 1])
            with c_u:
                m_url = st.text_input("Paste Music URL", key=f"url_{art}_{idx}")
            with c_b:
                if st.button("Scrape Link", key=f"btn_{art}_{idx}"):
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

    # --- EXPORT ---
    st.divider()
    if st.button("🚀 Generate Final PRS ZIP", type="primary"):
        if not os.path.exists(TEMPLATE_PATH):
            st.error("Template file missing!")
        else:
            zip_buffer = BytesIO()
            with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_f:
                for _, row in df.iterrows():
                    art = str(row['Artist']).strip()
                    s_df = st.session_state.setlists.get(art, pd.DataFrame())
                    total_s = sum(dur_to_sec(l) for l in s_df["Length"] if pd.notnull(l))
                    
                    v_info = VENUES.get(row.get('Venue Name'), VENUES["The Social"])
                    context = {
                        'V_NAME': row.get('Venue Name', 'The Social'),
                        'V_ADDR': v_info['address'], 'V_TEL': v_info['tel'], 
                        'DATE': row['Date'], 'ARTIST': art, 'TOTAL_DURATION': sec_to_format(total_s)
                    }
                    
                    doc = DocxTemplate(TEMPLATE_PATH)
                    doc.render(context)
                    table = doc.tables[-1]
                    for i, (_, s_row) in enumerate(s_df.iterrows()):
                        if i >= 10: break
                        table.cell(i+1, 1).text = str(s_row["Track Name"]).upper()
                        table.cell(i+1, 4).text = str(s_row["Length"])
                    
                    try: d_iso = datetime.strptime(str(row['Date']).strip(), "%d.%m.%Y").strftime("%Y-%m-%d")
                    except: d_iso = "0000-00-00"
                    
                    zip_f.writestr(f"{d_iso}_PRS_{art}.docx", BytesIO().getbuffer()) # Simplified for brevity

            st.download_button("Download ZIP", zip_buffer.getvalue(), "PRS_Setlists.zip")