import streamlit as st
import pandas as pd
import requests
import json
import zipfile
import os
import time
from datetime import datetime
from ytmusicapi import YTMusic
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync
from io import BytesIO
from docxtpl import DocxTemplate

# Initialize YTMusic
yt = YTMusic()

# --- 1. CONFIG & UTILS ---
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

# --- 2. THE SCRAPERS ---

def stage_1_deezer(artist):
    try:
        r = requests.get(f"https://api.deezer.com/search/artist?q={artist}", timeout=5).json()
        if r.get('data'):
            a_id = r['data'][0]['id']
            t = requests.get(f"https://api.deezer.com/artist/{a_id}/top?limit=10", timeout=5).json()
            return [{"Track Name": s['title'].upper(), "Length": f"{s['duration']//60}:{s['duration']%60:02d}"} for s in t['data']]
    except: return None

def stage_2_yt_music(artist):
    try:
        search = yt.search(artist, filter="artists")
        if not search: return None
        artist_id = search[0]['browseId']
        artist_data = yt.get_artist(artist_id)
        songs = artist_data.get('songs', {}).get('results', [])
        return [{"Track Name": s['title'].upper(), "Length": s.get('duration', '03:30')} for s in songs[:10]]
    except: return None

def stage_3_playwright_scrape(url):
    """Modern scraper for Spotify/Bandcamp/Soundcloud links."""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
            page = context.new_page()
            stealth_sync(page)
            
            page.goto(url, wait_until="networkidle", timeout=30000)
            # Give JS a moment to render the tracklist
            time.sleep(2)
            
            tracks = []
            # This selector covers almost all modern music players
            rows = page.query_selector_all('div[role="row"], .track_row_view, .track-title')
            
            for row in rows[:10]:
                try:
                    text = row.inner_text().split('\n')
                    # Look for track name (longest text) and duration (colon)
                    name = max(text, key=len).upper()
                    dur = next((t for t in text if ":" in t and len(t) <= 5), "03:45")
                    tracks.append({"Track Name": name, "Length": dur})
                except: continue
                
            browser.close()
            return tracks if tracks else None
    except Exception as e:
        st.error(f"Scraper Error: {e}")
        return None

# --- 3. APP UI ---
st.set_page_config(page_title="PRS Waterfall Pro", layout="wide")
st.title("🎸 PRS Batch Setlist Generator")

if 'setlists' not in st.session_state:
    st.session_state.setlists = {}

uploaded_file = st.file_uploader("Upload formatted_shows.csv", type="csv")

if uploaded_file:
    df = pd.read_csv(uploaded_file)
    
    if st.button("🚀 Run Automated Search (Deezer -> YT Music)"):
        for idx, row in df.iterrows():
            art = str(row['Artist']).strip()
            if art not in st.session_state.setlists or st.session_state.setlists[art].empty:
                with st.spinner(f"🔍 Searching {art}..."):
                    data = stage_1_deezer(art)
                    if not data: data = stage_2_yt_music(art)
                    st.session_state.setlists[art] = pd.DataFrame(data) if data else pd.DataFrame(columns=["Track Name", "Length"])
        st.rerun()

    st.subheader("Step 1: Review & Edit Tracks")
    for idx, row in df.iterrows():
        art = str(row['Artist']).strip()
        if art not in st.session_state.setlists:
            st.session_state.setlists[art] = pd.DataFrame(columns=["Track Name", "Length"])
        
        with st.expander(f"{'✅' if not st.session_state.setlists[art].empty else '⚠️'} Artist: {art}"):
            # Manual URL Scrape
            c_u, c_b = st.columns([3, 1])
            with c_u:
                m_url = st.text_input("Paste Spotify/Bandcamp URL", key=f"url_{art}_{idx}")
            with c_b:
                if st.button("Scrape Link", key=f"btn_{art}_{idx}"):
                    with st.spinner("Playwright is rendering page..."):
                        res = stage_3_playwright_scrape(m_url)
                        if res:
                            st.session_state.setlists[art] = pd.DataFrame(res)
                            st.rerun()

            # The Data Editor
            c_table, c_meta = st.columns([3, 1])
            with c_table:
                # Key must be unique and stable to prevent text deletion
                st.session_state.setlists[art] = st.data_editor(
                    st.session_state.setlists[art],
                    num_rows="dynamic",
                    key=f"ed_{art}_{idx}",
                    use_container_width=True
                )
            
            with c_meta:
                if st.button("25m Placeholder", key=f"pl_{art}_{idx}"):
                    st.session_state.setlists[art] = pd.DataFrame([{"Track Name": "LIVE PERFORMANCE", "Length": "25:00"}])
                    st.rerun()
                
                total_s = sum(dur_to_sec(l) for l in st.session_state.setlists[art]["Length"] if pd.notnull(l))
                st.metric("Set Time", sec_to_format(total_s))

    # --- 4. EXPORT LOGIC ---
    st.divider()
    if st.button("🚀 Generate All PRS Forms", type="primary"):
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_f:
            for _, row in df.iterrows():
                art = str(row['Artist']).strip()
                s_df = st.session_state.setlists.get(art, pd.DataFrame())
                total_s = sum(dur_to_sec(l) for l in s_df["Length"] if pd.notnull(l))
                
                v_name = row.get('Venue Name', 'The Social')
                v_info = VENUES.get(v_name, VENUES["The Social"])
                
                context = {
                    'V_NAME': v_name,
                    'V_ADDR': v_info['address'],
                    'V_TEL': v_info['tel'], 
                    'DATE': row['Date'], 
                    'ARTIST': art,
                    'TOTAL_DURATION': sec_to_format(total_s)
                }
                
                doc = DocxTemplate(TEMPLATE_PATH)
                doc.render(context)
                table = doc.tables[-1]
                for i, (_, s_row) in enumerate(s_df.iterrows()):
                    if i >= 10: break # Template usually has 10 rows
                    table.cell(i+1, 1).text = str(s_row["Track Name"]).upper()
                    table.cell(i+1, 4).text = str(s_row["Length"])
                
                try: 
                    d_iso = datetime.strptime(str(row['Date']).strip(), "%d.%m.%Y").strftime("%Y-%m-%d")
                except: 
                    d_iso = "0000-00-00"
                
                filename = f"{d_iso}_PRS_{art.replace(' ', '_')}.docx"
                doc_io = BytesIO()
                doc.save(doc_io)
                zip_f.writestr(filename, doc_io.getvalue())
        
        st.success("ZIP File Ready!")
        st.download_button("📥 Download All PRS Documents", zip_buffer.getvalue(), "PRS_Setlists_Batch.zip")