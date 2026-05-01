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

# Attempt to import Selenium - If it fails, the app still runs
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

# --- 2. THE WATERFALL SEARCH ---

def get_deezer_data(artist_name):
    try:
        search = requests.get(f"https://api.deezer.com/search/artist?q={artist_name}", timeout=5).json()
        if search.get('data'):
            a_id = search['data'][0]['id']
            tracks = requests.get(f"https://api.deezer.com/artist/{a_id}/top?limit=10", timeout=5).json()
            if tracks.get('data'):
                return [{"title": t['title'], "duration": f"{int(t['duration'])//60}:{int(t['duration'])%60:02d}", "seconds": int(t['duration'])} for t in tracks.get('data')]
    except: pass
    return []

def get_songs_waterfall(artist_name):
    # Stage 1: Deezer (Fastest API)
    songs = get_deezer_data(artist_name)
    if songs:
        return songs

    # Stage 2: Selenium (Only if environment supports it)
    if not SELENIUM_AVAILABLE:
        return []

    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    
    try:
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        
        # Spotify Check
        driver.get(f"https://open.spotify.com/search/{artist_name.replace(' ', '%20')}/artists")
        time.sleep(3)
        artists = driver.find_elements(By.CSS_SELECTOR, 'a[data-testid="artist-card-container"]')
        if artists and artists[0].text.split('\n')[0].lower() == artist_name.lower():
            artists[0].click()
            time.sleep(2)
            tracks = driver.find_elements(By.CSS_SELECTOR, 'div[data-testid="tracklist-row"]')[:10]
            results = [{"title": t.text.split('\n')[0], "duration": "3:30", "seconds": 210} for t in tracks]
            driver.quit()
            return results

        # Bandcamp Fallback
        driver.get(f"https://bandcamp.com/search?q={artist_name.replace(' ', '%20')}")
        time.sleep(2)
        bc_links = driver.find_elements(By.CSS_SELECTOR, ".result-info .heading a")
        if bc_links:
            bc_links[0].click()
            time.sleep(2)
            tracks = driver.find_elements(By.CSS_SELECTOR, ".track-title")[:10]
            results = [{"title": t.text, "duration": "4:00", "seconds": 240} for t in tracks]
            driver.quit()
            return results
            
        driver.quit()
    except:
        pass
    return []

# --- 3. CONTRACT PARSING ---

def normalize_pdf_date(date_str):
    if not date_str: return None
    months_map = {'jan': '01', 'feb': '02', 'mar': '03', 'apr': '04', 'may': '05', 'jun': '06',
                  'jul': '07', 'aug': '08', 'sep': '09', 'oct': '10', 'nov': '11', 'dec': '12'}
    found_month = next((m_num for m_name, m_num in months_map.items() if m_name in date_str.lower()), None)
    digits = re.findall(r'\d+', re.sub(r'(st|nd|rd|th)', '', date_str, flags=re.IGNORECASE))
    day = next((d.zfill(2) for d in digits if len(d) <= 2), None)
    year = next((d for d in digits if len(d) == 4), None)
    return f"{day}.{found_month}.{year}" if day and found_month and year else None

def extract_contract_data(zip_file):
    contract_db = {}
    headers = ["Contact Name:", "Contact Email:", "Performance Date(s):", "Group / Musician's Name:", "Venue Hire is"]
    header_pattern = "|".join([re.escape(h) for h in headers])
    
    with zipfile.ZipFile(zip_file) as z:
        for filename in z.namelist():
            if filename.lower().endswith(".pdf") and not filename.startswith("__MACOSX"):
                with z.open(filename) as f:
                    try:
                        reader = PdfReader(BytesIO(f.read()))
                        text = re.sub(r'\s+', ' ', " ".join([p.extract_text() for p in reader.pages]))
                        parts = re.split(f"({header_pattern})", text, flags=re.IGNORECASE)
                        data = {parts[i].strip().lower(): parts[i+1].strip() for i in range(1, len(parts), 2)}
                        
                        v_name = next((v for v in VENUES.keys() if v.lower() in text.lower()), "The Social")
                        norm_date = normalize_pdf_date(data.get("performance date(s):", ""))
                        if norm_date:
                            contract_db[norm_date] = {
                                "VENUE": v_name, "P_NAME": data.get("contact name:", "Unknown"),
                                "P_EMAIL": data.get("contact email:", ""), "P_TEL": "See Contract"
                            }
                    except: continue
    return contract_db

# --- 4. STREAMLIT UI ---

st.set_page_config(page_title="PRS Toolkit Pro", layout="wide")

if not SELENIUM_AVAILABLE:
    st.sidebar.warning("⚠️ Selenium not detected. Spotify/Bandcamp search disabled. Using Deezer only.")

page = st.sidebar.selectbox("Select Tool", ["Generate PRS Forms", "Convert Venue Export"])

if page == "Generate PRS Forms":
    st.title("🎸 PRS Batch Form Generator")
    uploaded_file = st.file_uploader("Upload Cleaned CSV", type="csv")
    
    if uploaded_file:
        df = pd.read_csv(uploaded_file)
        if st.button("Generate & Download ZIP"):
            zip_buffer = BytesIO()
            with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
                for _, row in df.iterrows():
                    songs = get_songs_waterfall(row['Artist'])
                    v_name = row.get('Venue Name', 'The Social')
                    v_info = VENUES.get(v_name, VENUES["The Social"])
                    
                    total_sec = sum(s['seconds'] for s in songs)
                    dur_str = f"{total_sec // 60}m {total_sec % 60:02d}s"
                    
                    context = {
                        'V_NAME': v_name, 
                        'V_ADDR': row.get('Venue Address', v_info['address']),
                        'V_TEL': v_info['tel'], 
                        'DATE': row['Date'], 
                        'ARTIST': row['Artist'],
                        'P_NAME': row['Promoter Name'], 
                        'P_EMAIL': row['Promoter Email'],
                        'P_TEL': row.get('Promoter Tel', 'See Contract'), 
                        'POSITION': v_info['position'],
                        'TOTAL_DURATION': dur_str
                    }
                    
                    doc = DocxTemplate(TEMPLATE_PATH)
                    doc.render(context)
                    table = doc.tables[-1]
                    for i, s in enumerate(songs[:10]):
                        table.cell(i+1, 1).text = s['title'].upper()
                        table.cell(i+1, 4).text = s['duration']
                    
                    # ISO Filename Logic
                    try:
                        date_obj = datetime.strptime(str(row['Date']).strip(), "%d.%m.%Y")
                        date_iso = date_obj.strftime("%Y-%m-%d")
                    except:
                        date_iso = str(row['Date']).replace('.', '-')

                    filename = f"{date_iso}_PRS_{str(row['Artist']).replace(' ', '_')}.docx"
                    doc_io = BytesIO()
                    doc.save(doc_io)
                    zip_file.writestr(filename, doc_io.getvalue())
            
            st.download_button("📥 Download ZIP", zip_buffer.getvalue(), "PRS_Batch.zip")

elif page == "Convert Venue Export":
    st.title("📂 Venue Export & Contract Matcher")
    col1, col2 = st.columns(2)
    with col1: raw_upload = st.file_uploader("1. Upload Raw Venue CSV", type="csv")
    with col2: contract_zip = st.file_uploader("2. Upload ZIP of Hire Contracts", type="zip")

    if raw_upload:
        raw_upload.seek(0)
        temp = pd.read_csv(raw_upload, header=None, nrows=50)
        try:
            h_idx = temp[temp.eq("The Social").any(axis=1)].index[0]
            raw_upload.seek(0)
            raw_df = pd.read_csv(raw_upload, skiprows=h_idx, header=None)
            cleaned = raw_df[[3, 5]].copy()
            cleaned.columns = ['Artist', 'Date']
            cleaned = cleaned[cleaned['Artist'].notna() & (cleaned['Artist'].str.len() > 2)]
            cleaned = cleaned[~cleaned['Artist'].str.contains("Admissions|categories|Licensee|Details", na=False)].drop_duplicates()
            
            for col in ['Venue Name', 'Venue Address', 'Promoter Name', 'Promoter Email', 'Promoter Tel']: cleaned[col] = ""

            if contract_zip:
                contracts = extract_contract_data(contract_zip)
                for idx, row in cleaned.iterrows():
                    d = str(row['Date']).strip()
                    if d in contracts:
                        info = contracts[d]
                        cleaned.at[idx, 'Venue Name'] = info['VENUE']
                        cleaned.at[idx, 'Venue Address'] = VENUES.get(info['VENUE'], VENUES["The Social"])['address']
                        cleaned.at[idx, 'Promoter Name'] = info['P_NAME']
                        cleaned.at[idx, 'Promoter Email'] = info['P_EMAIL']
                        cleaned.at[idx, 'Promoter Tel'] = info['P_TEL']

            st.data_editor(cleaned, num_rows="dynamic", use_container_width=True)
        except: st.error("CSV Format Error")