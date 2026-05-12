import streamlit as st
import pandas as pd
import requests
import json
import zipfile
import os
import time
from datetime import datetime
from ytmusicapi import YTMusic
from bs4 import BeautifulSoup
from io import BytesIO
from docxtpl import DocxTemplate

# Initialize YTMusic
yt = YTMusic()

# --- 1. CONFIGURATION & VENUES ---
VENUES = {
    "The Social": {"address": "5 Little Portland Street, London, W1W 7JD", "tel": "020 7636 4992", "position": "Venue Manager"},
    "The Windmill Brixton": {"address": "22 Blenheim Gardens, London, SW2 5BZ", "tel": "020 8671 0700", "position": "Promoter"}
}
TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "PRS SETLIST TEMPLATE.docx")

# --- 2. MATH HELPERS ---
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

# --- 3. THE WATERFALL ENGINES ---

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

def stage_3_spotify_extract(url):
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        scripts = soup.find_all('script', type='application/ld+json')
        for script in scripts:
            data = json.loads(script.string)
            if 'track' in data:
                return [{"Track Name": t.get('name').upper(), "Length": t.get('duration', '03:30').replace('PT','').replace('M',':').replace('S','')} for t in data['track'][:10]]
    except: return None

# --- 4. APP INTERFACE ---
st.set_page_config(page_title="PRS Pro Automator", layout="wide")
st.title("🎸 PRS Batch Waterfall Generator")

uploaded_file = st.file_uploader("Upload formatted_shows.csv", type="csv")

if uploaded_file:
    df = pd.read_csv(uploaded_file)
    if 'setlists' not in st.session_state:
        st.session_state.setlists = {}

    # AUTO-SEARCH TRIGGER
    if st.button("🚀 Run Search Waterfall (Deezer + YT Music)"):
        for idx, row in df.iterrows():
            art = str(row['Artist']).strip()
            if art not in st.session_state.setlists or st.session_state.setlists[art].empty:
                with st.spinner(f"Finding tracks for {art}..."):
                    data = stage_1_deezer(art)
                    if not data: data = stage_2_yt_music(art)
                    st.session_state.setlists[art] = pd.DataFrame(data) if data else pd.DataFrame(columns=["Track Name", "Length"])
        st.rerun()

    # MANUAL REVIEW & STAGE 4 (EDITING)
    st.subheader("Step 1: Review and Edit Tracks")
    for idx, row in df.iterrows():
        art = str(row['Artist']).strip()
        if art not in st.session_state.setlists:
            st.session_state.setlists[art] = pd.DataFrame(columns=["Track Name", "Length"])
        
        with st.expander(f"{'✅' if not st.session_state.setlists[art].empty else '⚠️'} Artist: {art}"):
            c_top1, c_top2 = st.columns([3, 1])
            with c_top1:
                m_url = st.text_input("Stage 3: Paste Spotify URL Override", key=f"url_{art}")
            with c_top2:
                if st.button("Extract Link", key=f"scr_{art}"):
                    res = stage_3_spotify_extract(m_url)
                    if res: 
                        st.session_state.setlists[art] = pd.DataFrame(res)
                        st.rerun()

            c_table, c_meta = st.columns([3, 1])
            with c_table:
                # STAGE 4: MANUAL INPUT (State-safe)
                ed_df = st.data_editor(st.session_state.setlists[art], num_rows="dynamic", key=f"ed_{art}_{idx}", use_container_width=True)
                st.session_state.setlists[art] = ed_df
            
            with c_meta:
                if st.button("Set 25m Placeholder", key=f"pl_{art}"):
                    st.session_state.setlists[art] = pd.DataFrame([{"Track Name": "LIVE PERFORMANCE / ORIGINAL SONGS", "Length": "25:00"}])
                    st.rerun()
                
                total_s = sum(dur_to_sec(l) for l in st.session_state.setlists[art]["Length"] if pd.notnull(l))
                st.metric("Total Set Duration", sec_to_format(total_s))

    # --- 5. BATCH FILE GENERATION ---
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
                    
                    v_info = VENUES.get(row.get('Venue Name', 'The Social'), VENUES["The Social"])
                    context = {
                        'V_NAME': row.get('Venue Name', 'The Social'),
                        'V_ADDR': row.get('Venue Address', v_info['address']),
                        'V_TEL': v_info['tel'], 'DATE': row['Date'], 'ARTIST': art,
                        'TOTAL_DURATION': sec_to_format(total_s)
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
                    
                    filename = f"{d_iso}_PRS_{art.replace(' ', '_')}.docx"
                    doc_io = BytesIO()
                    doc.save(doc_io)
                    zip_f.writestr(filename, doc_io.getvalue())
            
            st.success("Batch Processing Complete!")
            st.download_button("📥 Download All Documents", zip_buffer.getvalue(), "PRS_Forms_Batch.zip")