import streamlit as st
import pandas as pd
import requests
import zipfile
import os
import re
from docxtpl import DocxTemplate
from io import BytesIO
from pypdf import PdfReader

# --- 1. CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_FILENAME = "PRS SETLIST TEMPLATE.docx"
TEMPLATE_PATH = os.path.join(BASE_DIR, TEMPLATE_FILENAME)

VENUES = {
    "The Social": {"address": "5 Little Portland Street", "postcode": "W1W 7JD", "tel": "020 7636 4992", "position": "Venue Manager"},
    "The Windmill Brixton": {"address": "22 Blenheim Gardens", "postcode": "SW2 5BZ", "tel": "020 8671 0700", "position": "Promoter"}
}

# --- 2. IMPROVED DATE NORMALIZER ---
def normalize_pdf_date(date_str):
    try:
        clean = re.sub(r'(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|st|nd|rd|th)', '', date_str, flags=re.IGNORECASE).strip()
        months = {
            'January': '01', 'February': '02', 'March': '03', 'April': '04', 'May': '05', 'June': '06',
            'July': '07', 'August': '08', 'September': '09', 'October': '10', 'November': '11', 'December': '12'
        }
        parts = clean.split()
        if len(parts) >= 3:
            d = parts[0].zfill(2)
            m = months.get(parts[1], '01')
            y = parts[2]
            return f"{d}.{m}.{y}"
    except: return None
    return None

# --- 3. IMPROVED CONTRACT PARSING ---
def extract_contract_data(zip_file):
    contract_db = {}
    with zipfile.ZipFile(zip_file) as z:
        for filename in z.namelist():
            if filename.endswith(".pdf") and not filename.startswith("__MACOSX"):
                with z.open(filename) as f:
                    pdf_stream = BytesIO(f.read())
                    try:
                        reader = PdfReader(pdf_stream)
                        # Extract text with layout to preserve some structure
                        text = ""
                        for page in reader.pages:
                            text += page.extract_text() + " "
                        
                        # Replace newlines with spaces to make regex easier across line breaks
                        text = text.replace('\n', ' ')
                        
                        # Use lookaheads to stop at the next logical field in the TKO contract
                        date_re = r"Performance Date\(s\):\s*(.*?)(?=\s*(?:Group /|Today’s|Times|Ticketing|$))"
                        name_re = r"Contact Name:\s*(.*?)(?=\s*(?:Contact Email|Performance|Today’s|$))"
                        
                        date_match = re.search(date_re, text, re.IGNORECASE)
                        name_match = re.search(name_re, text, re.IGNORECASE)
                        
                        if date_match and name_match:
                            raw_date = date_match.group(1).strip()
                            contact_name = name_match.group(1).strip()
                            
                            normalized = normalize_pdf_date(raw_date)
                            if normalized:
                                contract_db[normalized] = {
                                    "P_NAME": contact_name,
                                    "P_ADDR": "Tokyo Industries / TKO Live",
                                    "P_TEL": "See Contract"
                                }
                    except: continue
    return contract_db

# --- 4. HELPERS ---
def get_deezer_data(artist_name):
    try:
        search = requests.get(f"https://api.deezer.com/search/artist?q={artist_name}").json()
        if search.get('data'):
            a_id = search['data'][0]['id']
            tracks = requests.get(f"https://api.deezer.com/artist/{a_id}/top?limit=10").json()
            return [{"title": t['title'], "duration": f"{int(t['duration'])//60}:{int(t['duration'])%60:02d}", "seconds": int(t['duration'])} for t in tracks.get('data', [])]
    except: return []
    return []

# --- 5. UI ---
st.set_page_config(page_title="PRS Toolkit Pro", page_icon="🎸", layout="wide")
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
                    songs = get_deezer_data(row['Artist'])
                    v_info = VENUES.get(row['Venue'], {"address": "", "postcode": "", "tel": "", "position": "Promoter"})
                    dur = f"{sum(s['seconds'] for s in songs) // 60}m {sum(s['seconds'] for s in songs) % 60:02d}s"
                    context = {
                        'V_NAME': row['Venue'], 'V_ADDR': v_info['address'], 'V_POST': v_info['postcode'], 'V_TEL': v_info['tel'],
                        'DATE': row['Date'], 'ARTIST': row['Artist'], 'P_NAME': row['Promoter Name'], 
                        'P_ADDR': row['Promoter Address'], 'P_TEL': row['Promoter Tel'], 'POSITION': v_info['position'], 'TOTAL_DURATION': dur
                    }
                    doc = DocxTemplate(TEMPLATE_PATH); doc.render(context)
                    table = doc.tables[-1]
                    for i, s in enumerate(songs):
                        table.cell(i+1, 1).text = s['title'].upper()
                        table.cell(i+1, 4).text = s['duration']
                    doc_io = BytesIO(); doc.save(doc_io)
                    zip_file.writestr(f"PRS_{str(row['Artist']).replace(' ', '_')}.docx", doc_io.getvalue())
            st.download_button("📥 Download ZIP", zip_buffer.getvalue(), "PRS_Batch.zip")

elif page == "Convert Venue Export":
    st.title("📂 Venue Export & Contract Matcher")
    col1, col2 = st.columns(2)
    with col1: raw_upload = st.file_uploader("1. Upload Raw Venue CSV", type="csv")
    with col2: contract_zip = st.file_uploader("2. Upload ZIP of Hire Contracts", type="zip")

    if raw_upload:
        # Move back to start of file after