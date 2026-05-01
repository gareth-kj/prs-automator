import streamlit as st
import pandas as pd
import requests
import zipfile
import os
from docxtpl import DocxTemplate
from io import BytesIO

# --- 1. CONFIGURATION & PATHS ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_FILENAME = "PRS SETLIST TEMPLATE.docx"
TEMPLATE_PATH = os.path.join(BASE_DIR, TEMPLATE_FILENAME)

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

# --- 2. HELPER FUNCTIONS ---
def get_deezer_data(artist_name):
    try:
        search = requests.get(f"https://api.deezer.com/search/artist?q={artist_name}").json()
        if search.get('data'):
            a_id = search['data'][0]['id']
            tracks = requests.get(f"https://api.deezer.com/artist/{a_id}/top?limit=10").json()
            results = []
            for t in tracks.get('data', []):
                sec = int(t['duration'])
                results.append({"title": t['title'], "duration": f"{sec // 60}:{sec % 60:02d}", "seconds": sec})
            return results
    except: return []
    return []

def format_seconds(total_seconds):
    return f"{total_seconds // 60}m {total_seconds % 60:02d}s"

# --- 3. UI NAVIGATION ---
st.set_page_config(page_title="PRS Toolkit", page_icon="🎸", layout="wide")
page = st.sidebar.selectbox("Select Tool", ["Generate PRS Forms", "Convert Venue Export"])

# --- PAGE: GENERATE PRS FORMS ---
if page == "Generate PRS Forms":
    st.title("🎸 PRS Batch Form Generator")
    
    with st.sidebar:
        st.header("System Check")
        if os.path.exists(TEMPLATE_PATH): st.success("✅ Template Found")
        else: st.error("❌ Template Missing")

    uploaded_file = st.file_uploader("Upload Cleaned CSV", type="csv")

    if uploaded_file:
        df = pd.read_csv(uploaded_file)
        st.dataframe(df.head(), use_container_width=True)

        if st.button("Generate & Download All"):
            zip_buffer = BytesIO()
            with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
                progress_bar = st.progress(0)
                for index, row in df.iterrows():
                    artist, venue_name = str(row['Artist']), str(row['Venue'])
                    songs = get_deezer_data(artist)
                    total_dur = format_seconds(sum(s['seconds'] for s in songs))
                    v_info = VENUES.get(venue_name, {"address": "", "postcode": "", "tel": "", "position": "Promoter"})

                    context = {
                        'V_NAME': venue_name, 'V_ADDR': v_info['address'], 'V_POST': v_info['postcode'], 'V_TEL': v_info['tel'],
                        'DATE': str(row['Date']), 'ARTIST': artist, 'P_NAME': str(row['Promoter Name']),
                        'P_ADDR': str(row['Promoter Address']), 'P_POST': str(row['Promoter Postcode']),
                        'P_TEL': str(row['Promoter Tel']), 'POSITION': v_info['position'], 'TOTAL_DURATION': total_dur
                    }

                    doc = DocxTemplate(TEMPLATE_PATH)
                    doc.render(context)
                    table = doc.tables[-1] 
                    for i, song in enumerate(songs):
                        table.cell(i