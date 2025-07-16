# ✅ Streamlit Business Finder – FINAL VERSION with Google Maps links + stable CRM sync using SerpAPI

import streamlit as st
import pandas as pd
from urllib.parse import quote_plus
from datetime import datetime
import gspread
from google.oauth2 import service_account
from serpapi import GoogleSearch

st.set_page_config(page_title="Local Business Finder", layout="wide")
st.title("🔎 Datavue Business Finder")

# Confirm secrets loaded
st.write("✅ Loaded secrets:", list(st.secrets.keys()))

# Google Sheets setup
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = service_account.Credentials.from_service_account_info(
    st.secrets["google_service_account"], scopes=scope
)
client = gspread.authorize(creds)
sheet = client.open_by_url("https://docs.google.com/spreadsheets/d/1A0AXN6o3qrPn38XQwnkx_StTAtGQ9M97FJA-2rW3Omo/edit")
crm_worksheet = sheet.worksheet("CRM")

# UI Inputs
postcode = st.text_input("Enter postcode", "DA16")
keywords = st.text_input("Search keywords (comma-separated)", "plumber, electrician, locksmith")
radius = st.slider("Search radius (miles)", 1, 20, 5)
search_button = st.button("Search")

# Search Logic using SerpAPI

def fetch_leads(postcode, keyword):
    search = GoogleSearch({
        "q": f"{keyword} near {postcode}",
        "location": postcode,
        "hl": "en",
        "gl": "uk",
        "api_key": st.secrets["serpapi_key"]
    })
    results = search.get_dict()

    leads = []
    for place in results.get("local_results", []):
        name = place.get("title", "")
        maps_review_url = place.get("gps_coordinates", {}).get("link") or f"https://www.google.com/maps/search/?api=1&query={quote_plus(name + ' ' + postcode)}"

        leads.append({
            "Business Name": f"[📍 {name}]({maps_review_url})",
            "Review Score": place.get("rating", ""),
            "Total Reviews": place.get("reviews", ""),
            "Location": postcode,
            "Address": place.get("address", ""),
            "Phone": place.get("phone", ""),
            "Website": place.get("website", ""),
            "Reviews": place.get("description", ""),
            "Email": "",
            "Scraped On": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "Notes": ""
        })
    return leads

# Main execution
if search_button:
    all_keywords = [k.strip() for k in keywords.split(",") if k.strip()]
    all_results = []
    for kw in all_keywords:
        with st.spinner(f"Searching '{kw}' near {postcode}..."):
            leads = fetch_leads(postcode, kw)
            all_results.extend(leads)

    if all_results:
        df = pd.DataFrame(all_results)
        st.success(f"✅ Found {len(df)} results")
        st.dataframe(df, use_container_width=True)

        if st.button("⬆️ Push to CRM"):
            existing_names = [row[0] for row in crm_worksheet.get_all_values()[1:]]
            new_rows = [list(r.values()) for _, r in df.iterrows() if r["Business Name"] not in existing_names]

            if new_rows:
                crm_worksheet.append_rows(new_rows)
                st.success(f"✅ Pushed {len(new_rows)} new rows to CRM")
            else:
                st.info("No new businesses to add.")
    else:
        st.warning("No results found.")
