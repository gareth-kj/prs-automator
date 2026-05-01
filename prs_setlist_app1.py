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

# --- 2. WATERFALL SEARCH (Aggressive Logic) ---

def get_deezer_data(artist_name):
    try:
        search = requests.get(f"https://api.deezer.com/search/artist?q={artist_name}", timeout=5).json()
        if search.get('data'):
            # Grab the first artist match
            a_id = search['data'][0]['id']
            tracks = requests.get(f"https://api.deezer.com/artist/{a_id}/top?limit=10", timeout=5).json()
            if tracks.get('data') and len(tracks['data']) > 0:
                return [{"title": t['title'], "duration": f"{int(t['duration'])//60}:{int(t['duration'])%60:02d}", "seconds": int(t['duration'])} for t in tracks.get('data')]
    except: pass
    return []

def get_songs_waterfall(artist_name):
    # Stage 1: Deezer 
    songs = get_deezer_data(artist_name)
    if songs and len(songs) > 0:
        return songs

    # Stage 2: Spotify (Selenium)
    if SELENIUM_AVAILABLE:
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        
        try:
            driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
            # Search Spotify via Google indexing for better direct access
            driver.get(f"https://open.spotify.com/search/{artist_name.replace(' ', '%20')}/artists")
            time.sleep(4)
            
            # Check for Artist Card
            artists = driver.find_elements(By.CSS_SELECTOR, 'a[data-testid="artist-card-container"]')
            if artists:
                # Get the name of the first result
                found_name = artists[0].text.split('\n')[0].lower()
                # Strict check to ensure we don't pull a famous artist for a niche one
                if found_name == artist_name.lower():
                    artists[0].click()
                    time.sleep(3)
                    # Scrape track names
                    track_rows = driver.find_elements(By.CSS_SELECTOR, 'div[data-testid="tracklist-row"]')[:10]
                    if track_rows:
                        spotify_songs = []
                        for row in track_rows:
                            try:
                                title = row.find_element(By.CSS_SELECTOR, 'div[role="gridcell"] img').get_attribute('alt')
                                spotify_songs.append({"title": title.replace("Album cover art for ", ""), "duration": "3:45", "seconds": 225})
                            except: continue
                        if spotify_songs:
                            driver.quit()
                            return spotify_songs

            # Stage 3: Bandcamp (Fallback if Spotify match fails)
            driver.get(f"https://bandcamp.com/search?q={artist_name.replace(' ', '%20')}")
            time.sleep(2)
            bc_links = driver.find_elements(By.CSS_SELECTOR, ".result-info .heading a")
            if bc_links:
                bc_links[0].click()
                time.sleep(2)
                tracks = driver.find_elements(By.CSS_SELECTOR, ".track-title")[:10]
                if tracks:
                    bc_songs = [{"title": t.text, "duration": "4:15", "seconds": 255} for t in tracks if t.text]
                    driver.quit()
                    return bc_songs
            
            driver.quit()
        except Exception as e:
            if 'driver' in locals(): driver.quit()
    
    return []

# --- 3. CONTRACT PARSING & NORMALIZATION ---

def normalize_pdf_date(date_str):
    if not date_str: return None
    months = {'jan': '01', 'feb': '02', 'mar': '03', 'apr': '04', 'may': '05', 'jun': '06',
              'jul': '07', 'aug': '08', 'sep': '09', 'oct': '10', 'nov': '11', 'dec': '12'}
    found_m = next((m_v for m_k, m_v in months.items() if m_k in date_str.lower()), None)
    nums = re.findall(r'\d+', re.sub(r'(st|nd|rd|th)', '', date_str, flags=re.IGNORECASE))
    day = next((n.zfill(2) for n in nums if len(n) <= 2), None)
    year = next((n for n in nums if len(n) == 4), None)
    return f"{day}.{found_m}.{year}" if day and found_m and year else None

def extract_contract_data(zip_file):
    db = {}
    headers = ["Contact Name:", "Contact Email:", "Performance Date(s):", "Group / Musician's Name:"]
    pattern = "|".join([re.escape(h) for h in headers])
    with zipfile.ZipFile(zip_file) as z:
        for f_name in z.namelist():
            if f_name.lower().endswith(".pdf") and not f_name.startswith("__MACOSX"):
                with z.open(f_name) as f:
                    try:
                        reader = PdfReader(BytesIO(f.read()))
                        text = re.sub(r'\s+', ' ', " ".join([p.extract_text() for p in reader.pages]))
                        parts = re.split(f"({pattern})", text, flags=re.IGNORECASE)
                        data = {parts[i].strip().lower(): parts[i+1].strip() for i in range(1, len(parts), 2)}
                        v_name = next((v for v in VENUES.keys() if v.lower() in text.lower()), "The Social")
                        norm_d = normalize_pdf_date(data.get("performance date(s):", ""))
                        if norm_d:
                            db[norm_d] = {"VENUE": v_name, "P_NAME": data.get("contact name:", "Unknown"),
                                          "P_EMAIL": data.get("contact email:", ""), "P_TEL": "See Contract"}
                    except: continue
    return db

# --- 4. STREAMLIT INTERFACE ---

st.set_page_config(page_title="PRS Toolkit Pro", layout="wide", page_icon="🎸")

if not SELENIUM_AVAILABLE:
    st.sidebar.error("🚨 Selenium is NOT active. Spotify & Bandcamp search will be skipped.")

tab1, tab2 = st.tabs(["🎸 Generate PRS Forms", "📂 Convert Venue Export"])

with tab1:
    st.header("Batch Generator")
    csv_file = st.file_uploader("Upload Formatted CSV", type="csv", key="gen_csv")
    if csv_file:
        df = pd.read_csv(csv_file)
        if st.button("Start Waterfall Search & Generate ZIP"):
            zip_out = BytesIO()
            with zipfile.ZipFile(zip_out, "a", zipfile.ZIP_DEFLATED, False) as zip_f:
                progress = st.progress(0)
                for idx, row in df.iterrows():
                    st.write(f"Searching for: **{row['Artist']}**...")
                    songs = get_songs_waterfall(row['Artist'])
                    
                    v_info = VENUES.get(row.get('Venue Name', 'The Social'), VENUES["The Social"])
                    total_s = sum(s['seconds'] for s in songs)
                    dur_label = f"{total_s // 60}m {total_s % 60:02d}s"
                    
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
                    
                    # Filename: YYYY-MM-DD_PRS_Artist.docx
                    try:
                        d_obj = datetime.strptime(str(row['Date']).strip(), "%d.%m.%Y")
                        d_iso = d_obj.strftime("%Y-%m-%d")
                    except:
                        d_iso = str(row['Date']).replace('.', '-')

                    f_name = f"{d_iso}_PRS_{str(row['Artist']).replace(' ', '_')}.docx"
                    d_io = BytesIO()
                    doc.save(d_io)
                    zip_f.writestr(f_name, d_io.getvalue())
                    progress.progress((idx + 1) / len(df))
            
            st.download_button("📥 Download ZIP", zip_out.getvalue(), "PRS_Batch.zip")

with tab2:
    st.header("Contract Matcher")
    c1, c2 = st.columns(2)
    with c1: raw_csv = st.file_uploader("Upload Raw Venue CSV", type="csv")
    with c2: raw_zip = st.file_uploader("Upload Contracts ZIP", type="zip")

    if raw_csv:
        raw_csv.seek(0)
        temp = pd.read_csv(raw_csv, header=None, nrows=50)
        try:
            idx = temp[temp.eq("The Social").any(axis=1)].index[0]
            raw_csv.seek(0)
            df_c = pd.read_csv(raw_csv, skiprows=idx, header=None)
            df_c = df_c[[3, 5]].copy()
            df_c.columns = ['Artist', 'Date']
            df_c = df_c[df_c['Artist'].notna() & (df_c['Artist'].str.len() > 2)].drop_duplicates()
            
            for col in ['Venue Name', 'Venue Address', 'Promoter Name', 'Promoter Email', 'Promoter Tel']: df_c[col] = ""

            if raw_zip:
                contracts = extract_contract_data(raw_zip)
                for i, r in df_c.iterrows():
                    dt = str(r['Date']).strip()
                    if dt in contracts:
                        inf = contracts[dt]
                        df_c.at[i, 'Venue Name'] = inf['VENUE']
                        df_c.at[i, 'Venue Address'] = VENUES.get(inf['VENUE'])['address']
                        df_c.at[i, 'Promoter Name'] = inf['P_NAME']
                        df_c.at[i, 'Promoter Email'] = inf['P_EMAIL']
                        df_c.at[i, 'Promoter Tel'] = inf['P_TEL']

            st.data_editor(df_c, num_rows="dynamic", use_container_width=True)
        except: st.error("Format error in Venue CSV.")