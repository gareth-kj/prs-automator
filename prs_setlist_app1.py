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

# Venue database for auto-filling addresses
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
    """Fetches top 10 tracks from Deezer API."""
    try:
        search = requests.get(f"https://api.deezer.com/search/artist?q={artist_name}").json()
        if search.get('data'):
            a_id = search['data'][0]['id']
            tracks = requests.get(f"https://api.deezer.com/artist/{a_id}/top?limit=10").json()
            results = []
            for t in tracks.get('data', []):
                sec = int(t['duration'])
                results.append({
                    "title": t['title'], 
                    "duration": f"{sec // 60}:{sec % 60:02d}",
                    "seconds": sec
                })
            return results
    except:
        return []
    return []

def format_seconds(total_seconds):
    """Formats total seconds into MMm SSs for the set duration box."""
    return f"{total_seconds // 60}m {total_seconds % 60:02d}s"

# --- 3. UI NAVIGATION ---
st.set_page_config(page_title="PRS Toolkit", page_icon="🎸", layout="wide")
page = st.sidebar.selectbox("Select Tool", ["Generate PRS Forms", "Convert Venue Export"])

# --- PAGE: GENERATE PRS FORMS ---
if page == "Generate PRS Forms":
    st.title("🎸 PRS Batch Form Generator")
    st.markdown("Upload your cleaned CSV to generate populated Word documents.")
    
    with st.sidebar:
        st.header("System Check")
        if os.path.exists(TEMPLATE_PATH):
            st.success("✅ Template Found")
        else:
            st.error("❌ Template Missing: Upload 'PRS SETLIST TEMPLATE.docx' to GitHub")

    uploaded_file = st.file_uploader("Upload Cleaned CSV", type="csv")

    if uploaded_file:
        df = pd.read_csv(uploaded_file)
        st.dataframe(df.head(), use_container_width=True)

        if st.button("Generate & Download All ZIP"):
            zip_buffer = BytesIO()
            with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                for index, row in df.iterrows():
                    artist = str(row['Artist'])
                    venue_name = str(row['Venue'])
                    status_text.text(f"Processing: {artist}...")

                    # 1. Fetch Data
                    songs = get_deezer_data(artist)
                    total_dur = format_seconds(sum(s['seconds'] for s in songs))
                    v_info = VENUES.get(venue_name, {"address": "", "postcode": "", "tel": "", "position": "Promoter"})

                    # 2. Map Template Context
                    context = {
                        'V_NAME': venue_name,
                        'V_ADDR': v_info['address'],
                        'V_POST': v_info['postcode'],
                        'V_TEL': v_info['tel'],
                        'DATE': str(row['Date']),
                        'ARTIST': artist,
                        'P_NAME': str(row['Promoter Name']),
                        'P_ADDR': str(row['Promoter Address']),
                        'P_POST': str(row['Promoter Postcode']),
                        'P_TEL': str(row['Promoter Tel']),
                        'POSITION': v_info['position'],
                        'TOTAL_DURATION': total_dur
                    }

                    # 3. Fill Document
                    try:
                        doc = DocxTemplate(TEMPLATE_PATH)
                        doc.render(context)

                        # Fill Performer details duration box (Table 5 in original template)
                        try:
                            perf_table = doc.tables[4] 
                            perf_table.cell(2, 1).text = total_dur
                        except: pass

                        # Fill the Setlist Table (The last table)
                        table = doc.tables[-1] 
                        for i, song in enumerate(songs):
                            table.cell(i+1, 1).text = song['title'].upper()
                            table.cell(i+1, 4).text = song['duration']

                        doc_io = BytesIO()
                        doc.save(doc_io)
                        safe_name = f"{artist}_{venue_name}".replace(" ", "_").replace("/", "-")
                        zip_file.writestr(f"PRS_{safe_name}.docx", doc_io.getvalue())
                    except Exception as e:
                        st.error(f"Error creating document for {artist}: {e}")
                    
                    progress_bar.progress((index + 1) / len(df))

            status_text.text("Batch Complete!")
            st.download_button("📥 Download ZIP Archive", zip_buffer.getvalue(), "PRS_Batch_Results.zip", "application/zip")

# --- PAGE: CONVERT VENUE EXPORT ---
elif page == "Convert Venue Export":
    st.title("📂 Venue Export Converter")
    st.markdown("Upload the raw **'Review Form.csv'** to collapse duplicate ticket rows into unique show entries.")

    raw_upload = st.file_uploader("Upload Raw Venue CSV", type="csv")

    if raw_upload:
        # 1. Load raw data skipping the header rows
        raw_df = pd.read_csv(raw_upload, skiprows=14, header=None)
        
        # 2. Select: Col 0=Venue, Col 3=Artist, Col 5=Date
        cleaned_df = raw_df[[0, 3, 5]].copy()
        cleaned_df.columns = ['Venue', 'Artist', 'Date']
        
        # 3. Data Cleaning
        cleaned_df['Artist'] = cleaned_df['Artist'].astype(str).str.strip()
        cleaned_df = cleaned_df[~cleaned_df['Artist'].isin(['nan', '', 'None'])]