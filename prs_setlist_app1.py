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

# --- 1. GLOBAL CONFIG & PATHS ---
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(os.getcwd(), "pw-browsers")
TEMPLATE_PATH = os.path.join(os.getcwd(), "PRS SETLIST TEMPLATE.docx")

VENUES = {
    "The Social": {"address": "5 Little Portland Street, London, W1W 7JD", "tel": "020 7636 4992"},
    "The Windmill Brixton": {"address": "22 Blenheim Gardens, London, SW2 5BZ", "tel": "020 8671 0700"}
}

# --- 2. TOOLS & APIS ---
try:
    from ytmusicapi import YTMusic
    yt = YTMusic()
except:
    yt = None

def dur_to_sec(dur_str):
    try:
        if ":" in str(dur_str):
            m, s = map(int, str(dur_str).split(":"))
            return (m * 60) + s
        return 0
    except: return 0

def sec_to_format(total_sec):
    return f"{total_sec // 60}m {total_sec % 60:02d}s"

# --- 3. THE SCRAPER ENGINE ---
def stage_3_playwright_scrape(url):
    try:
        # Create local path if missing
        pw_path = os.environ["PLAYWRIGHT_BROWSERS_PATH"]
        if not os.path.exists(pw_path):
            os.makedirs(pw_path)
            
        # Check if browser is installed locally
        if not os.listdir(pw_path):
            with st.spinner("First-run: Installing Full Chromium..."):
                subprocess.run(["python", "-m", "playwright", "install", "chromium", "--with-deps"], check=True)

        from playwright.sync_api import sync_playwright
        from playwright_stealth import Stealth

        with sync_playwright() as p:
            # Explicitly use full browser, not headless shell
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
            context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36")
            page = context.new_page()
            
            Stealth().apply(page)
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(5) # Wait for table hydration
            
            tracks = []
            rows = page.query_selector_all('div[role="row"], .track_row_view, [data-testid="tracklist-row"], .tracklist-item')
            
            for row in rows[:10]:
                try:
                    text_parts = row.inner_text().split('\n')
                    clean_text = [t.strip() for t in text_parts if len(t.strip()) > 1]
                    if not clean_text: continue
                    
                    name = max(clean_text, key=len).upper()
                    dur = next((t for t in clean_text if ":" in t and len(t) <= 5), "03:30")
                    tracks.append({"Track Name": name, "Length": dur})
                except: continue
                
            browser.close()
            return tracks
    except Exception as e:
        st.error(f"Scraper Error: {e}")
        return None

# --- 4. STREAMLIT INTERFACE ---
st.set_page_config(page_title="PRS Waterfall Pro", layout="wide")
st.title("🎸 PRS Batch Setlist Generator")

if 'setlists' not in st.session_state:
    st.session_state.setlists = {}

uploaded_file = st.file_uploader("Upload formatted_shows.csv", type="csv")

if uploaded_file:
    df = pd.read_csv(uploaded_file)
    
    if st.button("🚀 Run Automation Waterfall (Deezer + YT Music)"):
        p_text = st.empty()
        p_bar = st.progress(0)
        
        for i, row in df.iterrows():
            art = str(row['Artist']).strip()
            p_text.text(f"Processing: {art}...")
            
            if art not in st.session_state.setlists or st.session_state.setlists[art].empty:
                data = None
                # Stage 1: Deezer API
                try:
                    r = requests.get(f"https://api.deezer.com/search/artist?q={art}", timeout=5).json()
                    a_id = r['data'][0]['id']
                    t = requests.get(f"https://api.deezer.com/artist/{a_id}/top?limit=10", timeout=5).json()
                    data = [{"Track Name": s['title'].upper(), "Length": f"{s['duration']//60}:{s['duration']%60:02d}"} for s in t['data']]
                except: pass
                
                # Stage 2: YT Music API
                if not data and yt:
                    try:
                        s = yt.search(art, filter="artists")[0]
                        songs = yt.get_artist(s['browseId'])['songs']['results']
                        data = [{"Track Name": sg['title'].upper(), "Length": sg.get('duration', '03:45')} for sg in songs[:10]]
                    except: pass
                
                st.session_state.setlists[art] = pd.DataFrame(data) if data else pd.DataFrame(columns=["Track Name", "Length"])
            
            p_bar.progress((i + 1) / len(df))
        st.rerun()

    # Manual Review Section
    for idx, row in df.iterrows():
        art = str(row['Artist']).strip()
        if art not in st.session_state.setlists:
            st.session_state.setlists[art] = pd.DataFrame(columns=["Track Name", "Length"])
            
        with st.expander(f"{'✅' if not st.session_state.setlists[art].empty else '⚠️'} Artist: {art}"):
            c_u, c_b = st.columns([3, 1])
            with c_u:
                m_url = st.text_input("Paste Link", key=f"u_{art}_{idx}")
            with c_b:
                if st.button("Scrape Link", key=f"b_{art}_{idx}"):
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
            st.metric("Total Duration", sec_to_format(total_s))

    # Export Logic
    st.divider()
    if st.button("🚀 Finalize & Generate ZIP", type="primary"):
        if not os.path.exists(TEMPLATE_PATH):
            st.error("Template file missing from GitHub!")
        else:
            zip_buffer = BytesIO()
            with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_f:
                for _, row in df.iterrows():
                    art = str(row['Artist']).strip()
                    s_df = st.session_state.setlists.get(art, pd.DataFrame())
                    total_s = sum(dur_to_sec(l) for l in s_df["Length"] if pd.notnull(l))
                    v_info = VENUES.get(row.get('Venue Name'), VENUES["The Social"])
                    
                    doc = DocxTemplate(TEMPLATE_PATH)
                    doc.render({
                        'V_NAME': row.get('Venue Name', 'The Social'),
                        'V_ADDR': v_info['address'], 'V_TEL': v_info['tel'],
                        'DATE': row['Date'], 'ARTIST': art, 'TOTAL_DURATION': sec_to_format(total_s)
                    })
                    
                    table = doc.tables[-1]
                    for i, (_, s_row) in enumerate(s_df.iterrows()):
                        if i >= 10: break
                        table.cell(i+1, 1).text = str(s_row["Track Name"]).upper()
                        table.cell(i+1, 4).text = str(s_row["Length"])
                    
                    try: d_iso = datetime.strptime(str(row['Date']), "%d.%m.%Y").strftime("%Y-%m-%d")
                    except: d_iso = "0000-00-00"
                    
                    doc_io = BytesIO()
                    doc.save(doc_io)
                    zip_f.writestr(f"{d_iso}_PRS_{art.replace(' ', '_')}.docx", doc_io.getvalue())
            
            st.download_button("📥 Download ZIP", zip_buffer.getvalue(), "PRS_Forms.zip")