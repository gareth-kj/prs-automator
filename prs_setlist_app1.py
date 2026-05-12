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

# Selenium Imports
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# --- 1. CONFIGURATION ---
VENUES = {
    "The Social": {"address": "5 Little Portland Street, London, W1W 7JD", "tel": "020 7636 4992", "position": "Venue Manager"},
    "The Windmill Brixton": {"address": "22 Blenheim Gardens, London, SW2 5BZ", "tel": "020 8671 0700", "position": "Promoter"}
}
TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "PRS SETLIST TEMPLATE.docx")

# --- 2. SEARCH ENGINES ---

def get_spotify_selenium(artist_name):
    """Stage 1: Spotify Selenium with Exact Match logic."""
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    try:
        # Search specifically for artists to reduce noise
        driver.get(f"https://open.spotify.com/search/{artist_name.replace(' ', '%20')}/artists")
        wait = WebDriverWait(driver, 8)
        
        # Locate artist cards
        artist_cards = wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, 'a[data-testid="artist-card-container"]')))
        
        for card in artist_cards:
            # Check the name inside the card
            found_name = card.text.split('\n')[0].strip().lower()
            if found_name == artist_name.lower():
                card.click()
                time.sleep(2)
                
                # Pull top 10 tracks
                tracks = driver.find_elements(By.CSS_SELECTOR, 'div[data-testid="tracklist-row"]')[:10]
                results = []
                for t in tracks:
                    title = t.find_element(By.CSS_SELECTOR, 'div[role="gridcell"] img').get_attribute('alt').replace("Album cover art for ", "")
                    results.append({"title": title, "duration": "3:30", "seconds": 210})
                return results
    except: pass
    finally: driver.quit()
    return []

def get_deezer_api(artist_name):
    """Stage 2: Deezer API fallback."""
    try:
        r = requests.get(f"https://api.deezer.com/search/artist?q={artist_name}", timeout=5).json()
        if r.get('data'):
            a_id = r['data'][0]['id']
            tracks = requests.get(f"https://api.deezer.com/artist/{a_id}/top?limit=10", timeout=5).json()
            return [{"title": t['title'], "duration": f"{int(t['duration'])//60}:{int(t['duration'])%60:02d}", "seconds": int(t['duration'])} for t in tracks.get('data', [])]
    except: pass
    return []

def get_bandcamp_selenium(artist_name):
    """Stage 3: Bandcamp Selenium fallback."""
    options = Options()
    options.add_argument("--headless")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    try:
        driver.get(f"https://bandcamp.com/search?q={artist_name.replace(' ', '%20')}")
        time.sleep(2)
        results = driver.find_elements(By.CSS_SELECTOR, ".result-info .heading a")
        if results:
            results[0].click()