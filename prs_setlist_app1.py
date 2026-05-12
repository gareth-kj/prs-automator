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

# --- 1. CONFIGURATION ---
VENUES = {
    "The Social": {"address": "5 Little Portland Street, London, W1W 7JD", "tel": "020 7636 4992", "position": "Venue Manager"},
    "The Windmill Brixton": {"address": "22 Blenheim Gardens, London, SW2 5BZ", "tel": "020 8671 0700", "position": "Promoter"}
}
TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "PRS SETLIST TEMPLATE.docx")

# --- 2. SEARCH ENGINES ---

def get_spotify_selenium(artist_name):
    """Stage 1: Spotify Selenium with Exact Match logic."""
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    try:
        # Search specifically for artists to reduce noise
        driver.get(f"https://open.spotify.com/search/{artist_name.replace(' ', '%20')}/artists")
        wait = WebDriverWait(driver, 8)
        
        # Locate artist cards
        artist_cards = wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, 'a[data-testid="artist-card-container"]')))
        
        for card in artist_cards:
            # Check the name inside the card
            found_name = card.text.split('\n')[0].strip().lower()
            if found_name == artist_name.lower():
                card.click()
                time.sleep(2)
                
                # Pull top 10 tracks
                tracks = driver.find_elements(By.CSS_SELECTOR, 'div[data-testid="tracklist-row"]')[:10]
                results = []
                for t in tracks:
                    title = t.find_element(By.CSS_SELECTOR, 'div[role="gridcell"] img').get_attribute('alt').replace("Album cover art for ", "")
                    results.append({"title": title, "duration": "3:30", "seconds": 210})
                return results
    except: pass
    finally: driver.quit()
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
    """Stage 3: Bandcamp Selenium fallback."""
    options = Options()
    options.add_argument("--headless")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    try:
        driver.get(f"https://bandcamp.com/search?q={artist_name.replace(' ', '%20')}")
        time.sleep(2)
        results = driver.find_elements(By.CSS_SELECTOR, ".result-info .heading a")
        if results:
            results[0].click()
            time.sleep(2)
            tracks = driver.find_elements(By.CSS_SELECTOR, ".track-title")[:10]
            return [{"title": t.text, "duration": "4:00", "seconds": 240} for t in tracks if t.text]
    except: pass
    finally: driver.quit()
    return []

def get_songs_waterfall(artist_name):
    st.write(f"🔍 Searching Spotify for **{artist_name}**...")
    res = get_spotify_selenium(artist_name)
    if res: return res
    
    st.write(f"⚠️ No Spotify match. Trying Deezer...")
    res = get_deezer_api(artist_name)
    if res: return res
    
    st.write(f"⚠️ No Deezer match. Trying Bandcamp...")
    return get_bandcamp_selenium(artist_name)

# --- 3. THE APP ---

st.set_page_config(page_title="PRS Toolkit", layout="wide")
st.title("🎸 PRS Batch Setlist Generator")

uploaded_file = st.file_uploader("Upload formatted_shows.csv", type="csv")

if uploaded_file:
    df = pd.read_csv(uploaded_file)
    if st.button("Generate Documents"):
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
            for _, row in df.iterrows():
                artist = row['Artist']
                songs = get_songs_waterfall(artist)
                
                v_info = VENUES.get(row.get('Venue Name', 'The Social'), VENUES["The Social"])
                total_sec = sum(s['seconds'] for s in songs)
                
                context = {
                    'V_NAME': row.get('Venue Name', 'The Social'), 'V_ADDR': v_info['address'],
                    'V_TEL': v_info['tel'], 'DATE': row['Date'], 'ARTIST': artist,
                    'P_NAME': row.get('Promoter Name', ''), 'P_EMAIL': row.get('Promoter Email', ''),
                    'TOTAL_DURATION': f"{total_sec // 60}m {total_sec % 60:02d}s"
                }
                
                doc = DocxTemplate(TEMPLATE_PATH)
                doc.render(context)
                
                # Fill song table in Word
                if songs:
                    table = doc.tables[-1]
                    for i, s in enumerate(songs[:10]):
                        table.cell(i+1, 1).text = s['title'].upper()
                        table.cell(i+1, 4).text = s['duration']
                
                # Filename logic: YYYY-MM-DD_PRS_Artist.docx
                try:
                    d_iso = datetime.strptime(str(row['Date']).strip(), "%d.%m.%Y").strftime("%Y-%m-%d")
                except: d_iso = str(row['Date']).replace('.', '-')
                
                filename = f"{d_iso}_PRS_{artist.replace(' ', '_')}.docx"
                doc_io = BytesIO()
                doc.save(doc_io)
                zip_file.writestr(filename, doc_io.getvalue())
                
        st.success("Batch Complete!")
        st.download_button("📥 Download ZIP", zip_buffer.getvalue(), "PRS_Setlists.zip")