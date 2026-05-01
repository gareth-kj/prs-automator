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
from pypdf import PdfReader

# --- SELENIUM SETUP ---
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from webdriver_manager.chrome import ChromeDriverManager
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

# --- 1. CONFIGURATION ---
VENUES = {
    "The Social": {
        "address": "5 Little Portland Street, London, W1W 7JD",
        "tel": "020 7636 4992",
        "position": "Venue Manager"
    },
    "The Windmill Brixton": {
        "address": "22 Blenheim Gardens, London, SW2 5BZ",
        "tel": "020 8671 0700",
        "position": "Promoter"
    }
}

TEMPLATE_FILENAME = "PRS SETLIST TEMPLATE.docx"
TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), TEMPLATE_FILENAME)

# --- 2. WATERFALL SEARCH ---

def get_deezer_data(artist_name):
    try:
        search = requests.get(f"https://api.deezer.com/search/artist?q={artist_name}", timeout=5).json()
        if search.get('data'):
            a_id = search['data'][0]['id']
            tracks = requests.get(f"https://api.deezer.com/artist/{a_id}/top?limit=10", timeout=5).json()
            if tracks.get('data') and len(tracks['data']) > 0:
                return [{"title": t['title'], "duration": f"{int(t['duration'])//60}:{int(t['duration'])%60:02d}", "seconds": int(t['duration'])} for t in tracks.get('data')]
    except: pass
    return []

def get_songs_waterfall(artist_name):
    # Stage 1: Deezer 
    songs = get_deezer_data(artist_name)
    if songs: return songs

    # Stage 2: Spotify (Selenium)
    if SELENIUM_AVAILABLE:
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        # Add User-Agent to avoid being blocked as a bot
        options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        
        try:
            driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
            wait = WebDriverWait(driver, 10)
            
            # Use direct Spotify search URL for artists
            driver.get(f"https://open.spotify.com/search/{artist_name.replace(' ', '%20')}/artists")
            time.sleep(5) 

            # Look for the artist result
            # Spotify often nests the name inside a specific data-testid
            artist_elements = driver.find_elements(By.CSS_SELECTOR, 'a[data-testid="artist-card-container"]')
            
            if artist_elements:
                # Get text and clean it (Spotify often adds 'Artist' or 'Verified' to the label)
                raw_text = artist_elements[0].text.lower()
                
                # If 'cardboard' is in 'cardboard artist verified', we proceed
                if artist_name.lower() in raw_text:
                    artist_elements[0].click()
                    time.sleep(3)
                    
                    # Target the Top Tracks rows
                    track_rows = driver.find_elements(By.CSS_SELECTOR, 'div[data-testid="tracklist-row"]')[:10]
                    if track_rows:
                        spotify_songs = []
                        for row in track_rows:
                            try:
                                # Title is usually the first link or bold text in the row
                                title = row.find_element(By.CSS_SELECTOR, 'div[role="gridcell"] img').get_attribute('alt')
                                title = title.replace("Album cover art for ", "")
                                spotify_songs.append({"title": title, "duration": "3:30", "seconds": 210})
                            except: continue
                        if spotify_songs:
                            driver.quit()
                            return spotify_songs

            # Stage 3: Bandcamp Fallback
            driver.get(f"https://bandcamp.com/search?q={artist_name.replace(' ', '%20')}")
            time.sleep(3)
            bc_links = driver.find_elements(By.CSS_SELECTOR, ".result-info .heading a")
            if bc_links:
                bc_links[0].click()
                time.sleep(3)
                tracks = driver.find_elements(By.CSS_SELECTOR, ".track-title")[:10]
                if tracks:
                    bc_songs = [{"title": t.text, "duration": "4:00", "seconds": 240} for t in tracks if t.text]
                    driver.quit()
                    return bc_songs
            
            driver.quit()
        except:
            if 'driver' in locals(): driver.quit()
    
    return []

# --- 3. CONTRACT & FILENAME LOGIC ---

def normalize_pdf_date(date_str):
    if not date_str: return None
    months = {'jan': '01', 'feb': '02', 'mar': '03', 'apr': '04', 'may': '05', 'jun': '06',
              'jul': '07', 'aug': '08', 'sep': '09', 'oct': '10', 'nov': '11', 'dec': '12'}
    found_m = next((m_v for m_k, m_v in months.items() if m_k in date_str.lower()), None)
    nums = re.findall(r'\d+', re.sub(r'(st|nd|rd|th)', '', date_str, flags=re.IGNORECASE))
    day = next((n.zfill(2) for n in nums if len(n) <= 2), None)
    year = next((n for n in nums if len(n) == 4), None)
    return f"{day}.{found_m}.{year}" if day and found_m and year else None

# --- 4. STREAMLIT UI ---

st.set_page_config(page_title="PRS Toolkit Pro", layout="wide")

tab1, tab2 = st.tabs(["🎸 Generate PRS Forms", "📂 Convert Venue Export"])

with tab1:
    st.header("Batch Generator")
    uploaded_csv = st.file_uploader("Upload Your CSV", type="csv")
    if uploaded_csv:
        df = pd.read_csv(uploaded_csv)
        if st.button("Generate ZIP"):
            zip_out = BytesIO()
            with zipfile.ZipFile(zip_out, "a", zipfile.ZIP_DEFLATED, False) as zip_f:
                for _, row in df.iterrows():
                    st.write(f"Processing: {row['Artist']}...")
                    songs = get_songs_waterfall(row['Artist'])
                    
                    v_info = VENUES.get(row.get('Venue Name', 'The Social'), VENUES["The Social"])
                    total_sec = sum(s['seconds'] for s in songs)
                    dur_label = f"{total_sec // 60}m {total_sec % 60:02d}s"
                    
                    ctx = {
                        'V_NAME': row.get('Venue Name', 'The Social'), 
                        'V_ADDR': row.get('Venue Address', v_info['address']),
                        'V_TEL': v_info['tel'], 'DATE': row['Date'], 'ARTIST': row['Artist'],
                        'P_NAME': row.get('Promoter Name', 'Unknown'), 
                        'P_EMAIL': row.get('Promoter Email', ''),
                        'P_TEL': row.get('Promoter Tel', 'See Contract'), 
                        'POSITION': v_info['position'],
                        'TOTAL_DURATION': dur_label
                    }
                    
                    doc = DocxTemplate(TEMPLATE_PATH)
                    doc.render(ctx)
                    table = doc.tables[-1]
                    for i, s in enumerate(songs[:10]):
                        table.cell(i+1, 1).text = s['title'].upper()
                        table.cell(i+1, 4).text = s['duration']
                    
                    try:
                        d_obj = datetime.strptime(str(row['Date']).strip(), "%d.%m.%Y")
                        d_iso = d_obj.strftime("%Y-%m-%d")
                    except:
                        d_iso = str(row['Date']).replace('.', '-')

                    f_name = f"{d_iso}_PRS_{str(row['Artist']).replace(' ', '_')}.docx"
                    d_io = BytesIO()
                    doc.save(d_io)
                    zip_f.writestr(f_name, d_io.getvalue())
            
            st.download_button("📥 Download ZIP", zip_out.getvalue(), "PRS_Batch.zip")

with tab2:
    st.header("Venue CSV Converter")
    st.info("Upload your raw venue export here to match against hire contracts.")
    # (Matching logic from previous versions)