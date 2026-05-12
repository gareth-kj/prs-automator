import streamlit as st
import pandas as pd
import requests
import zipfile
import os
import time
from datetime import datetime
from io import BytesIO
from docxtpl import DocxTemplate

# Selenium Imports
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium_stealth import stealth

# --- CONFIG & MATH ---
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

# --- SEARCH ENGINES ---

def get_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    if os.path.exists("/usr/bin/chromium"):
        options.binary_location = "/usr/bin/chromium"
        service = Service("/usr/bin/chromedriver")
    else:
        service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    stealth(driver, languages=["en-US", "en"], vendor="Google Inc.", platform="Win32", webgl_vendor="Intel Inc.", renderer="Intel Iris OpenGL Engine", fix_hairline=True)
    return driver

def run_waterfall(artist):
    # Stage 1: Deezer
    try:
        r = requests.get(f"https://api.deezer.com/search/artist?q={artist}", timeout=5).json()
        if r.get('data'):
            a_id = r['data'][0]['id']
            t = requests.get(f"https://api.deezer.com/artist/{a_id}/top?limit=10", timeout=5).json()
            return [{"Track Name": s['title'], "Length": f"{s['duration']//60}:{s['duration']%60:02d}"} for s in t['data']]
    except: pass

    # Stage 2: Spotify Selenium
    driver = None
    try:
        driver = get_driver()
        driver.get(f"https://open.spotify.com/search/{artist.replace(' ', '%20')}/artists")
        wait = WebDriverWait(driver, 10)
        cards = wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, 'a[data-testid="artist-card-container"]')))
        cards[0].click()
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'div[data-testid="tracklist-row"]')))
        rows = driver.find_elements(By.CSS_SELECTOR, 'div[data-testid="tracklist-row"]')[:10]
        songs = []
        for row in rows:
            title = row.find_element(By.CSS_SELECTOR, 'img').get_attribute('alt').replace("Album cover art for ", "")
            dur = row.find_elements(By.CSS_SELECTOR, 'div[role="gridcell"]')[-1].text
            songs.append({"Track Name": title, "Length": dur})
        if songs: return songs
    except: pass
    finally:
        if driver: driver.quit()

    # Stage 3: Bandcamp
    try:
        driver = get_driver()
        driver.get(f"https://bandcamp.com/search?q={artist.replace(' ', '%20')}")
        time.sleep(2)
        res = driver.find_elements(By.CSS_SELECTOR, ".result-info .heading a")
        if res:
            res[0].click()
            time.sleep(2)
            tracks = driver.find_elements(By.CSS_SELECTOR, ".track-title")[:10]
            return [{"Track Name": t.text, "Length": "04:00"} for t in tracks if t.text]
    except: pass
    finally:
        if driver: driver.quit()
    return []

# --- APP UI ---

st.set_page_config(page_title="PRS Automator", layout="wide")
st.title("🎸 PRS Setlist Batch Processor")

uploaded_file = st.file_uploader("Upload formatted_shows.csv", type="csv")

if uploaded_file:
    df = pd.read_csv(uploaded_file)
    if 'setlists' not in st.session_state:
        st.session_state.setlists = {}

    # AUTO-PROCESS ARTISTS
    for idx, row in df.iterrows():
        artist = str(row['Artist']).strip()
        if artist not in st.session_state.setlists:
            with st.spinner(f"🔍 Waterfall searching: {artist}..."):
                results = run_waterfall(artist)
                st.session_state.setlists[artist] = pd.DataFrame(results) if results else pd.DataFrame(columns=["Track Name", "Length"])

    # UI REVIEW
    st.subheader("Step 1: Review Automated Results")
    for idx, row in df.iterrows():
        artist = str(row['Artist']).strip()
        songs_df = st.session_state.setlists[artist]
        
        with st.expander(f"{'✅' if len(songs_df) > 0 else '⚠️'} Artist: {artist}", expanded=(len(songs_df) == 0)):
            col1, col2 = st.columns([3, 1])
            
            with col1:
                # Stage 4: Manual Input / Edit
                edited_df = st.data_editor(
                    songs_df,
                    num_rows="dynamic",
                    key=f"editor_{artist}_{idx}",
                    use_container_width=True
                )
                st.session_state.setlists[artist] = edited_df

            with col2:
                if st.button(f"25m Placeholder", key=f"pl_{idx}"):
                    st.session_state.setlists[artist] = pd.DataFrame([{"Track Name": "LIVE PERFORMANCE / ORIGINAL MATERIAL", "Length": "25:00"}])
                    st.rerun()
                
                total_s = sum(dur_to_sec(ln) for ln in st.session_state.setlists[artist]["Length"] if pd.notnull(ln))
                st.metric("Total Set Time", sec_to_format(total_s))

    # GENERATION
    st.divider()
    if st.button("🚀 Generate All PRS Forms", type="primary"):
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_f:
            for _, row in df.iterrows():
                art = str(row['Artist']).strip()
                s_df = st.session_state.setlists.get(art)
                total_s = sum(dur_to_sec(ln) for ln in s_df["Length"] if pd.notnull(ln))
                
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
        
        st.success("ZIP Ready!")
        st.download_button("📥 Download ZIP", zip_buffer.getvalue(), "PRS_Setlists.zip")