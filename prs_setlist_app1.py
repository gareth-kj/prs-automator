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

# --- 2. CONTRACT PARSING LOGIC ---
def extract_contract_data(zip_file):
    contract_db = {}
    with zipfile.ZipFile(zip_file) as z:
        for filename in z.namelist():
            # Skip hidden mac files or non-pdfs
            if filename.endswith(".pdf") and not filename.startswith("__MACOSX"):
                with z.open(filename) as f:
                    # Wrap in BytesIO to fix the EOF error
                    pdf_stream = BytesIO(f.read())
                    try:
                        reader = PdfReader(pdf_stream)
                        text = "".join([page.extract_text() for page in reader.pages])
                        
                        # Extract Data using Regex
                        date_match = re.search(r"Performance Date\(s\):\s*(.*)", text)
                        name_match = re.search(r"Contact Name:\s*(.*)", text)
                        
                        if date_match:
                            raw_date_str = date_match.group(1).strip()
                            name = name_match.group(1).strip() if name_match else "Unknown"
                            
                            # Standardize the date for matching (e.g. "29th June 2026")
                            # We strip the Day name (Monday) to make matching easier
                            clean_date = re.sub(r'^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s*', '', raw_date_str)
                            
                            contract_db[clean_date] = {
                                "P_NAME": name,
                                "P_ADDR": "Tokyo Industries / TKO Live",
                                "P_POST": "SE1 1RU",
                                "P_TEL": "See Contract"
                            }
                    except Exception as e:
                        st.warning(f"Could not read {filename}: {e}")
    return contract_db

# --- 3. HELPER FUNCTIONS ---
def get_deezer_data(artist_name):
    try:
        search = requests.get(f"https://api.deezer.com/search/artist?q={artist_name}").json()
        if search.get('data'):
            a_id = search['data'][0]['id']
            tracks = requests.get(f"https://api.deezer.com/artist/{a_id}/top?limit=10").json()
            return [{"title": t['title'], "duration": f"{int(t['duration'])//60}:{int(t['duration'])%60:02d}", "seconds": int(t['duration'])} for t in tracks.get('data', [])]
    except: return []
    return []

def format_seconds(total_seconds):
    return f"{total_seconds // 60}m {total_seconds % 60:02d}s"

# --- 4. UI ---
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
                    context = {
                        'V_NAME': row['Venue'], 'V_ADDR': v_info['address'], 'V_POST': v_info['postcode'], 'V_TEL': v_info['tel'],
                        'DATE': row['Date'], 'ARTIST': row['Artist'], 'P_NAME': row['Promoter Name'],
                        'P_ADDR': row['Promoter Address'], 'P_POST': row['Promoter Postcode'], 'P_TEL': row['Promoter Tel'],
                        'POSITION': v_info['position'], 'TOTAL_DURATION': format_seconds(sum(s['seconds'] for s in songs))
                    }
                    doc = DocxTemplate(TEMPLATE_PATH); doc.render(context)
                    table = doc.tables[-1]
                    for i, s in enumerate(songs):
                        table.cell(i+1, 1).text = s['title'].upper()
                        table.cell(i+1, 4).text = s['duration']
                    doc_io = BytesIO(); doc.save(doc_io)
                    zip_file.writestr(f"PRS_{row['Artist']}.docx", doc_io.getvalue())
            st.download_button("📥 Download ZIP", zip_buffer.getvalue(), "PRS_Batch.zip")

elif page == "Convert Venue Export":
    st.title("📂 Venue Export & Contract Matcher")
    col1, col2 = st.columns(2)
    with col1:
        raw_upload = st.file_uploader("1. Upload Raw Venue CSV", type="csv")
    with col2:
        contract_zip = st.file_uploader("2. Upload ZIP of Hire Contracts", type="zip")

    if raw_upload:
        # Load raw data (Review Form.csv)
        raw_df = pd.read_csv(raw_upload, skiprows=14, header=None)
        cleaned_df = raw_df[[0, 3, 5]].copy()
        cleaned_df.columns = ['Venue', 'Artist', 'Date']
        cleaned_df = cleaned_df.dropna(subset=['Artist']).drop_duplicates(subset=['Artist', 'Date'])
        
        for col in ['Promoter Name', 'Promoter Address', 'Promoter Postcode', 'Promoter Tel']:
            cleaned_df[col] = ""

        if contract_zip:
            contracts = extract_contract_data(contract_zip)
            
            for idx, row in cleaned_df.iterrows():
                csv_date = str(row['Date']) # e.g. 29.06.2026
                
                # Attempt to match. Since CSV is DD.MM.YYYY and PDF is "29th June 2026",
                # a simple substring match might fail. We check if day and year match.
                day = csv_date.split('.')[0]
                year = csv_date.split('.')[-1]
                
                for contract_date, info in contracts.items():
                    if day in contract_date and year in contract_date:
                        cleaned_df.at[idx, 'Promoter Name'] = info['P_NAME']
                        cleaned_df.at[idx, 'Promoter Address'] = info['P_ADDR']
                        cleaned_df.at[idx, 'Promoter Postcode'] = info['P_POST']
                        cleaned_df.at[idx, 'Promoter Tel'] = info['P_TEL']

        st.success(f"Processed {len(cleaned_df)} shows.")
        edited_df = st.data_editor(cleaned_df, num_rows="dynamic", use_container_width=True)
        csv_buffer = edited_df.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Download Formatted CSV", csv_buffer, "formatted_shows.csv", "text/csv")