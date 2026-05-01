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

# Internal Database for Venue Details
VENUES = {
    "The Social": {
        "address": "5 Little Portland Street, London",
        "postcode": "W1W 7JD",
        "tel": "020 7636 4992",
        "position": "Venue Manager"
    },
    "The Windmill Brixton": {
        "address": "22 Blenheim Gardens, London",
        "postcode": "SW2 5BZ",
        "tel": "020 8671 0700",
        "position": "Promoter"
    }
}

# --- 2. THE BULLETPROOF DATE NORMALIZER ---
def normalize_pdf_date(date_str):
    if not date_str: return None
    try:
        months_map = {
            'jan': '01', 'feb': '02', 'mar': '03', 'apr': '04', 'may': '05', 'jun': '06',
            'jul': '07', 'aug': '08', 'sep': '09', 'oct': '10', 'nov': '11', 'dec': '12'
        }
        found_month = None
        for m_name, m_num in months_map.items():
            if m_name in date_str.lower():
                found_month = m_num
                break
        
        clean_text = re.sub(r'(st|nd|rd|th)', '', date_str, flags=re.IGNORECASE)
        digits = re.findall(r'\d+', clean_text)
        day, year = None, None
        for d in digits:
            if len(d) <= 2: day = d.zfill(2)
            elif len(d) == 4: year = d
        
        if day and found_month and year:
            return f"{day}.{found_month}.{year}"
    except: return None
    return None

# --- 3. CONTRACT PARSING ---
def extract_contract_data(zip_file):
    contract_db = {}
    with zipfile.ZipFile(zip_file) as z:
        for filename in z.namelist():
            if filename.lower().endswith(".pdf") and not filename.startswith("__MACOSX"):
                with z.open(filename) as f:
                    pdf_stream = BytesIO(f.read())
                    try:
                        reader = PdfReader(pdf_stream)
                        full_text = " ".join([p.extract_text() for p in reader.pages])
                        full_text = re.sub(r'\s+', ' ', full_text)
                        
                        # Identify Venue from internal database
                        matched_venue = "Unknown Venue"
                        for v_name in VENUES.keys():
                            if v_name.lower() in full_text.lower():
                                matched_venue = v_name
                                break

                        # Regex for Name, Email, and Date
                        stop_at = r"(?=\s*(?:Group /|Today|Times|Ticketing|Venue|$))"
                        date_re = r"Performance Date\(s\):\s*(.*?)" + stop_at
                        name_re = r"Contact Name:\s*(.*?)" + stop_at
                        email_re = r"Contact Email:\s*(.*?)" + stop_at
                        
                        d_m = re.search(date_re, full_text, re.IGNORECASE)
                        n_m = re.search(name_re, full_text, re.IGNORECASE)
                        e_m = re.search(email_re, full_text, re.IGNORECASE)
                        
                        if d_m:
                            norm_date = normalize_pdf_date(d_m.group(1).strip())
                            if norm_date:
                                contract_db[norm_date] = {
                                    "VENUE": matched_venue,
                                    "P_NAME": n_m.group(1).strip() if n_m else "Unknown",
                                    "P_EMAIL": e_m.group(1).strip() if e_m else "",
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
                    v_info = VENUES.get(row['Venue Name'], {"address": "", "postcode": "", "tel": "", "position": "Promoter"})
                    dur = f"{sum(s['seconds'] for s in songs) // 60}m {sum(s['seconds'] for s in songs) % 60:02d}s"
                    
                    context = {
                        'V_NAME': row['Venue Name'], 'V_ADDR': row['Venue Address'], 'V_POST': v_info['postcode'], 'V_TEL': v_info['tel'],
                        'DATE': row['Date'], 'ARTIST': row['Artist'], 
                        'P_NAME': row['Promoter Name'], 'P_EMAIL': row['Promoter Email'], 'P_TEL': row['Promoter Tel'],
                        'POSITION': v_info['position'], 'TOTAL_DURATION': dur
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
        raw_upload.seek(0)
        temp_df = pd.read_csv(raw_upload, header=None, nrows=50)
        try:
            # Find data start row
            header_idx = temp_df[temp_df.eq("The Social").any(axis=1)].index[0]
            raw_upload.seek(0)
            raw_df = pd.read_csv(raw_upload, skiprows=header_idx, header=None)
            
            cleaned_df = raw_df[[3, 5]].copy() # Only take Artist and Date from CSV
            cleaned_df.columns = ['Artist', 'Date']
            cleaned_df = cleaned_df[cleaned_df['Artist'].notna() & (cleaned_df['Artist'].str.len() > 2)]
            cleaned_df = cleaned_df[~cleaned_df['Artist'].str.contains("Admissions|categories|Licensee|Details|name|Event /", na=False)]
            cleaned_df = cleaned_df.drop_duplicates(subset=['Artist', 'Date'])
            
            # Setup new columns
            new_cols = ['Venue Name', 'Venue Address', 'Promoter Name', 'Promoter Email', 'Promoter Tel']
            for col in new_cols: cleaned_df[col] = ""

            if contract_zip:
                contracts = extract_contract_data(contract_zip)
                for idx, row in cleaned_df.iterrows():
                    csv_date = str(row['Date']).strip()
                    if csv_date in contracts:
                        info = contracts[csv_date]
                        v_details = VENUES.get(info['VENUE'], {"address": "Address Unknown", "tel": ""})
                        
                        cleaned_df.at[idx, 'Venue Name'] = info['VENUE']
                        cleaned_df.at[idx, 'Venue Address'] = v_details['address']
                        cleaned_df.at[idx, 'Promoter Name'] = info['P_NAME']
                        cleaned_df.at[idx, 'Promoter Email'] = info['P_EMAIL']
                        cleaned_df.at[idx, 'Promoter Tel'] = info['P_TEL']

            st.success(f"Processed {len(cleaned_df)} unique shows.")
            edited_df = st.data_editor(cleaned_df, num_rows="dynamic", use_container_width=True)
            csv_buffer = edited_df.to_csv(index=False).encode('utf-8')
            st.download_button("📥 Download Formatted CSV", csv_buffer, "formatted_shows.csv", "text/csv")
        except: st.error("Error identifying data start in CSV.")