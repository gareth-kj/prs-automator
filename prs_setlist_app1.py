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

# Selenium Imports
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.core.os_manager import ChromeType

# --- 1. CONFIGURATION ---
VENUES = {
    "The Social": {"address": "5 Little Portland Street, London, W1W 7JD", "tel": "020 7636 4992", "position": "Venue Manager"},
    "The Windmill Brixton": {"address": "22 Blenheim Gardens, London, SW2 5BZ", "tel": "020 8671 0700", "position": "Promoter"}
}
TEMPLATE_FILENAME = "PRS SETLIST TEMPLATE.docx"
TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), TEMPLATE_FILENAME)

# --- 2. SEARCH ENGINES ---

def get_driver():
    """Sets up a headless Chrome driver compatible with Streamlit's Debian environment."""
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    
    # On Streamlit Cloud, chromium is installed to /usr/bin/chromium
    # and the driver is installed to /usr/bin/chromedriver
    try:
        service = Service("/usr/bin/chromedriver")
        options.binary_location = "/usr/bin/chromium"
        return webdriver.Chrome(service=service, options=options)
    except:
        # Fallback for local testing
        return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

def get_spotify_selenium(artist_name):
    """Stage 1: Spotify Selenium - Exact Match Only."""
    driver = get_driver()
    try:
        driver.get(f"https://open.spotify.com/search/{artist_name.replace(' ', '%20')}/artists")
        wait = WebDriverWait(driver, 12)
        
        # Wait for artist results
        artist_cards = wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, 'a[data-testid="artist-card-container"]')))
        
        for card in artist_cards:
            found_name = card.text.split('\n')[0].strip().lower()
            # STRICT EXACT MATCH
            if found_name == artist_name.lower():
                card.click()
                time.sleep(3)
                
                track_elements = driver.find_elements(By.CSS_SELECTOR, 'div[data-testid="tracklist-row"]')[:10]
                songs = []
                for t in track_elements:
                    try:
                        title = t.find_element(By.CSS_SELECTOR, 'div[role="gridcell"] img').get_attribute('alt').replace("Album cover art for ", "")
                        songs.append({"title": title, "duration": "3:30", "seconds": 210})
                    except: continue
                if songs: 
                    driver.quit()
                    return songs
    except Exception as e:
        st.error(f"Spotify Scrape Error for {artist_name}: {str(e)}")
    finally:
        driver.quit()
    return []

def get_deezer_api(artist_name):
    """Stage 2: Deezer API fallback."""
    try:
        r = requests.get(f"https://api.deezer.com/search/artist?q={artist_name}", timeout=5).json()
        if r.get('data'):
            a_id = r['data'][0]['id']
            tracks = requests.get(f"https://api.deezer.com/artist/{a_id}/top?limit=10", timeout=5).json()
            return [{"title": t['title'], "duration": f"{int(t['duration'])//60}:{int(t['duration'])%60:02d}", "seconds": int(t['duration'])} for t in tracks.get('data', [])]
    except: pass
    return []

def get_bandcamp_selenium(artist_name):
    """Stage 3: Bandcamp fallback."""
    driver = get_driver()
    try:
        driver.get(f"https://bandcamp.com/search?q={artist_name.replace(' ', '%20')}")
        time.sleep(3)
        results = driver.find_elements(By.CSS_SELECTOR, ".result-info .heading a")
        if results:
            results[0].click()
            time.sleep(3)
            tracks = driver.find_elements(By.CSS_SELECTOR, ".track-title")[:10]
            res = [{"title": t.text, "duration": "4:00", "seconds": 240} for t in tracks if t.text]
            driver.quit()
            return res
    except: pass
    finally: driver.quit()
    return []

def get_songs_waterfall(artist_name):
    st.write(f"🔍 Searching Spotify for **{artist_name}**...")
    res = get_spotify_selenium(artist_name)
    if res: return res
    
    st.write(f"⚠️ No exact Spotify match. Trying Deezer...")
    res = get_deezer_api(artist_name)
    if res: return res
    
    st.write(f"⚠️ No Deezer match. Trying Bandcamp...")
    return get_bandcamp_selenium(artist_name)

# --- 3. THE APP INTERFACE ---

st.set_page_config(page_title="PRS Toolkit", layout="wide")
st.title("🎸 PRS Batch Setlist Generator")

if not os.path.exists(TEMPLATE_PATH):
    st.error(f"Missing file: {TEMPLATE_FILENAME}. Please upload it to your GitHub repo.")

uploaded_file = st.file_uploader("Upload formatted_shows.csv", type="csv")

if uploaded_file:
    df = pd.read_csv(uploaded_file)
    if st.button("Generate Documents"):
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
            progress_bar = st.progress(0)
            
            for idx, row in df.iterrows():
                artist = str(row['Artist']).strip()
                songs = get_songs_waterfall(artist)
                
                v_name = row.get('Venue Name', 'The Social')
                v_info = VENUES.get(v_name, VENUES["The Social"])
                total_sec = sum(s['seconds'] for s in songs)
                
                context = {
                    'V_NAME': v_name, 'V_ADDR': row.get('Venue Address', v_info['address']),
                    'V_TEL': v_info['tel'], 'DATE': row['Date'], 'ARTIST': artist,
                    'P_NAME': row.get('Promoter Name', ''), 'P_EMAIL': row.get('Promoter Email', ''),
                    'TOTAL_DURATION': f"{total_sec // 60}m {total_sec % 60:02d}s"
                }
                
                doc = DocxTemplate(TEMPLATE_PATH)
                doc.render(context)
                
                if songs:
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
                
                progress_bar.progress((idx + 1) / len(df))
                
        st.success("Batch Complete!")
        st.download_button("📥 Download ZIP", zip_buffer.getvalue(), "PRS_Setlists.zip")