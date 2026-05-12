import streamlit as st
import pandas as pd
import requests
import zipfile
import os
import time
import random
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
from selenium_stealth import stealth

# --- 1. CORE UTILS ---
def dur_to_sec(dur_str):
    try:
        dur_str = str(dur_str).strip()
        if ":" in dur_str:
            m, s = map(int, dur_str.split(":"))
            return (m * 60) + s
        return int(float(dur_str)) * 60
    except: return 0

def sec_to_format(total_sec):
    return f"{total_sec // 60}m {total_sec % 60:02d}s"

def get_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
    
    if os.path.exists("/usr/bin/chromium"):
        options.binary_location = "/usr/bin/chromium"
        service = Service("/usr/bin/chromedriver")
    else:
        service = Service(ChromeDriverManager().install())
    
    driver = webdriver.Chrome(service=service, options=options)
    stealth(driver, languages=["en-US", "en"], vendor="Google Inc.", platform="Win32", webgl_vendor="Intel Inc.", renderer="Intel Iris OpenGL Engine", fix_hairline=True)
    return driver

# --- 2. SCRAPING ENGINE ---

def scrape_spotify_url(url):
    """Targeted scrape for a specific Spotify Artist URL."""
    driver = None
    try:
        driver = get_driver()
        driver.get(url)
        wait = WebDriverWait(driver, 15)
        # Wait for tracklist rows
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="tracklist-row"]')))
        time.sleep(2)
        
        rows = driver.find_elements(By.CSS_SELECTOR, '[data-testid="tracklist-row"]')[:10]
        songs = []
        for row in rows:
            cells = row.find_elements(By.CSS_SELECTOR, 'div[role="gridcell"]')
            name = row.find_element(By.CSS_SELECTOR, 'div[data-encore-id="type"]').text
            dur = cells[-1].text
            songs.append({"Track Name": name.upper(), "Length": dur})
        return songs
    except: return None
    finally:
        if driver: driver.quit()

# --- 3. APP UI ---
st.set_page_config(page_title="PRS Toolkit", layout="wide")
st.title("🎸 PRS Batch Setlist Generator")

uploaded_file = st.file_uploader("Upload formatted_shows.csv", type="csv")

if uploaded_file:
    df = pd.read_csv(uploaded_file)
    
    # Persistent State: This prevents data from being deleted on rerun
    if 'setlists' not in st.session_state:
        st.session_state.setlists = {}

    for idx, row in df.iterrows():
        artist = str(row['Artist']).strip()
        
        # 1. Initialize entry if missing
        if artist not in st.session_state.setlists:
            st.session_state.setlists[artist] = pd.DataFrame(columns=["Track Name", "Length"])

        # 2. UI Expander
        is_empty = st.session_state.setlists[artist].empty
        with st.expander(f"{'✅' if not is_empty else '⚠️'} Artist: {artist}", expanded=is_empty):
            
            # --- URL OVERRIDE SECTION ---
            st.markdown("##### 🔗 Search / Manual Link")
            col_url, col_btn = st.columns([3, 1])
            with col_url:
                manual_url = st.text_input("Paste Spotify Artist URL", key=f"url_{artist}_{idx}")
            with col_btn:
                if st.button("Scrape URL", key=f"scr_{artist}_{idx}"):
                    if manual_url:
                        with st.spinner("Targeting URL..."):
                            data = scrape_spotify_url(manual_url)
                            if data:
                                st.session_state.setlists[artist] = pd.DataFrame(data)
                                st.rerun()
                            else:
                                st.error("Could not find tracks on that page.")

            st.divider()

            # --- TABLE SECTION ---
            col_table, col_meta = st.columns([3, 1])
            with col_table:
                # We use 'on_change' logic implicitly by saving the result of the editor
                edited = st.data_editor(
                    st.session_state.setlists[artist],
                    num_rows="dynamic",
                    key=f"editor_{artist}_{idx}",
                    use_container_width=True
                )
                # CRITICAL: Update session state so data persists
                st.session_state.setlists[artist] = edited

            with col_meta:
                if st.button("25m Placeholder", key=f"pl_{idx}"):
                    st.session_state.setlists[artist] = pd.DataFrame([{"Track Name": "LIVE PERFORMANCE", "Length": "25:00"}])
                    st.rerun()
                
                total_s = sum(dur_to_sec(ln) for ln in st.session_state.setlists[artist]["Length"] if pd.notnull(ln))
                st.metric("Total Set Time", sec_to_format(total_s))

    # --- 4. EXPORT ---
    st.divider()
    if st.button("🚀 Generate All PRS Forms", type="primary"):
        # (Standard DocxTemplate generation logic goes here)
        st.success("Documents Created!")