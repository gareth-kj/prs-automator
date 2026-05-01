import streamlit as st
import pandas as pd
import requests
import zipfile
import os
from docxtpl import DocxTemplate
from io import BytesIO

# --- 1. FILE PATH CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_FILENAME = "PRS SETLIST TEMPLATE.docx"
TEMPLATE_PATH = os.path.join(BASE_DIR, TEMPLATE_FILENAME)

# --- 2. VENUE DATABASE ---
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

# --- 3. HELPER FUNCTIONS ---
def get_deezer_data(artist_name):
    try:
        # Search for artist and get ID
        search = requests.get(f"https://api.deezer.com/search/artist?q={artist_name}").json()
        if search.get('data'):
            a_id = search['data'][0]['id']
            # Fetch exactly 10 tracks [cite: 25, 26]
            tracks = requests.get(f"https://api.deezer.com/artist/{a_id}/top?limit=10").json()
            results = []
            for t in tracks.get('data', []):
                sec = int(t['duration'])
                duration_str = f"{sec // 60}:{sec % 60:02d}"
                results.append({
                    "title": t['title'], 
                    "duration": duration_str,
                    "seconds": sec
                })
            return results
    except Exception:
        return []
    return []

def format_seconds(total_seconds):
    """Converts total seconds into a readable MM:SS format for the set duration."""
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes}m {seconds:02d}s"

# --- 4. STREAMLIT UI ---
st.set_page_config(page_title="PRS Bulk Automator", page_icon="🎸")
st.title("🎸 PRS Batch Form Generator")

with st.sidebar:
    st.header("System Check")
    if os.path.exists(TEMPLATE_PATH):
        st.success(f"✅ Template Found: {TEMPLATE_FILENAME}")
    else:
        st.error(f"❌ Template Missing at: {TEMPLATE_PATH}")

uploaded_file = st.file_uploader("Upload your list of shows (CSV)", type="csv")

if uploaded_file:
    df = pd.read_csv(uploaded_file)
    st.subheader("Preview of Uploaded Data")
    st.dataframe(df.head(), use_container_width=True)

    if st.button("Generate & Download All PRS Forms"):
        if not os.path.exists(TEMPLATE_PATH):
            st.error("Template file not found.")
        else:
            zip_buffer = BytesIO()
            with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                for index, row in df.iterrows():
                    artist = str(row['Artist'])
                    venue_name = str(row['Venue'])
                    status_text.text(f"Processing: {artist}...")

                    # 1. Fetch exactly 10 songs and calculate duration
                    songs = get_deezer_data(artist)
                    total_set_seconds = sum(s['seconds'] for s in songs)
                    formatted_total_duration = format_seconds(total_set_seconds)

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
                        'TOTAL_DURATION': formatted_total_duration
                    }

                    # 3. Fill Document
                    try:
                        doc = DocxTemplate(TEMPLATE_PATH)
                        doc.render(context)

                        # Fill Performer details duration box 
                        # In the template provided, Performer details start at table index 4
                        try:
                            perf_table = doc.tables[4] 
                            perf_table.cell(2, 1).text = formatted_total_duration
                        except:
                            pass

                        # Fill the Setlist Table (The last table in the doc) [cite: 26]
                        table = doc.tables[-1] 
                        for i, song in enumerate(songs):
                            # table.cell(row, col) - Title is Col 1, Duration is Col 4 [cite: 26]
                            table.cell(i+1, 1).text = song['title'].upper()
                            table.cell(i+1, 4).text = song['duration']

                        doc_io = BytesIO()
                        doc.save(doc_io)
                        filename = f"PRS_{artist.replace(' ', '_')}_{venue_name.replace(' ', '_')}.docx"
                        zip_file.writestr(filename, doc_io.getvalue())
                    
                    except Exception as e:
                        st.error(f"Error for {artist}: {e}")
                    
                    progress_bar.progress((index + 1) / len(df))

            st.success(f"Generated {len(df)} documents.")
            st.download_button(
                label="📥 Download ZIP Archive",
                data=zip_buffer.getvalue(),
                file_name="PRS_Batch_Returns.zip",
                mime="application/zip"
            )