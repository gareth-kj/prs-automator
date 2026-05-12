import streamlit as st
import pandas as pd
import requests
import zipfile
import os
import time
import random
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

# --- THE ENGINES ---

def get_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    # Humanizing the footprint
    options.add_argument(f"user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
    
    if os.path.exists("/usr/bin/chromium"):
        options.binary_location = "/usr/bin/chromium"
        service = Service("/usr/bin/chromedriver")
    else:
        service = Service(ChromeDriverManager().install())
    
    driver = webdriver.Chrome(service=service, options=options)
    stealth(driver, languages=["en-US", "en"], vendor="Google Inc.", platform="Win32", webgl_vendor="Intel Inc.", renderer="Intel Iris OpenGL Engine", fix_hairline=True)
    return driver

def run_waterfall(artist):
    # --- STAGE 1: DEEZER ---
    try:
        r = requests.get(f"https://api.deezer.com/search/artist?q={artist}", timeout=5).json()
        if r.get('data'):
            a_id = r['data'][0]['id']
            t = requests.get(f"https://api.deezer.com/artist/{a_id}/top?limit=10", timeout=5).json()
            if t.get('data'):
                return [{"Track Name": s['title'], "Length": f"{s['duration']//60}:{s['duration']%60:02d}"} for s in t['data']]
    except: pass

    # --- STAGE 2: SPOTIFY (With Throttling) ---
    # We add a random sleep to stop the IP from being flagged
    time.sleep(random.uniform(3.5, 7.0)) 
    
    driver = None
    try:
        driver = get_driver()
        driver.get(f"https://open.spotify.com/search/{artist.replace(' ', '%20')}/artists")
        wait = WebDriverWait(driver, 20)
        
        # Click first artist result
        artist_card = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'a[data-testid="artist-card-container"]')))
        artist_card.click()
        
        # Wait for tracks
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="tracklist-row"]')))
        time.sleep(2)
        
        rows = driver.find_elements(By.CSS_SELECTOR, '[data-testid="tracklist-row"]')[:10]
        songs = []
        for row in rows:
            cells = row.find_elements(By.CSS_SELECTOR, 'div[role="gridcell"]')
            # Track name usually in cell 1 or 2 depending on view
            name = row.find_element(By.CSS_SELECTOR, 'div[data-encore-id="type"]').text
            dur = cells[-1].text
            songs.append({"Track Name": name.upper(), "Length": dur})
        if songs: return songs
    except: pass
    finally:
        if driver: driver.quit()

    return []

# --- APP UI ---
st.set_page_config(page_title="PRS Setlist Automator", layout="wide")
st.title("🎸 PRS Setlist Batch Processor")

uploaded_file = st.file_uploader("Upload formatted_shows.csv", type="csv")

if uploaded_file:
    df = pd.read_csv(uploaded_file)
    if 'setlists' not in st.session_state:
        st.session_state.setlists = {}

    # Sequential Processing with Breaks
    if st.button("🔍 Start Automated Search"):
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for idx, row in df.iterrows():
            artist = str(row['Artist']).strip()
            if artist not in st.session_state.setlists or st.session_state.setlists[artist].empty:
                status_text.text(f"Searching for {artist} (Stage 1 & 2)...")
                results = run_waterfall(artist)
                st.session_state.setlists[artist] = pd.DataFrame(results) if results else pd.DataFrame(columns=["Track Name", "Length"])
                progress_bar.progress((idx + 1) / len(df))
        status_text.text("Search Cycle Complete.")

    # Review Section
    for idx, row in df.iterrows():
        artist = str(row['Artist']).strip()
        # Initialize if button wasn't clicked
        if artist not in st.session_state.setlists:
            st.session_state.setlists[artist] = pd.DataFrame(columns=["Track Name", "Length"])
            
        songs_df = st.session_state.setlists[artist]
        
        with st.expander(f"{'✅' if not songs_df.empty else '⚠️'} Artist: {artist}", expanded=songs_df.empty):
            c1, c2 = st.columns([3, 1])
            with c1:
                # Stage 4: Manual Table
                new_df = st.data_editor(songs_df, num_rows="dynamic", key=f"ed_{artist}_{idx}", use_container_width=True)
                st.session_state.setlists[artist] = new_df
            with c2:
                if st.button(f"25m Placeholder", key=f"pl_{idx}"):
                    st.session_state.setlists[artist] = pd.DataFrame([{"Track Name": "LIVE PERFORMANCE / ORIGINAL", "Length": "25:00"}])
                    st.rerun()
                
                total_s = sum(dur_to_sec(ln) for ln in st.session_state.setlists[artist]["Length"] if pd.notnull(ln))
                st.metric("Total Set Time", sec_to_format(total_s))

    # ZIP Logic... (standard)