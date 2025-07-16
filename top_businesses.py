import streamlit as st
import pandas as pd
from datetime import datetime
import gspread
from google.oauth2 import service_account
from serpapi import GoogleSearch

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

# Streamlit UI
st.set_page_config(page_title="Local Business Finder", layout="wide")
st.title("🔎 Datavue Business Finder")

postcode = st.text_input("Enter postcode", "DA16")
keywords = st.text_input("Search keywords (comma-separated)", "plumber, electrician, locksmith")
radius = st.slider("Search radius (miles)", 1, 20, 5)
search_button = st.button("Search")

def fetch_leads(postcode, keyword):
    params = {
        "engine": "google_maps",
        "q": keyword,
        "type": "search",
        "location": postcode,
        "api_key": st.secrets["serpapi_key"]
    }

    search = GoogleSearch(params)
    results = search.get_dict()
    businesses = results.get("local_results", [])

    formatted = []
    for b in businesses:
        formatted.append({
            "Business Name": f"[{b.get('title', '')}]({b.get('link', '')})",
            "Link": b.get("link", ""),
            "Snippet": b.get("description", ""),
            "Keyword": keyword,
            "Postcode": postcode,
            "Scraped On": datetime.now().strftime("%Y-%m-%d %H:%M")
        })

    return formatted

if search_button:
    all_keywords = [k.strip() for k in keywords.split(",") if k.strip()]
    all_results = []
    for kw in all_keywords:
        with st.spinner(f"Searching '{kw}' near {postcode}..."):
            leads = fetch_leads(postcode, kw)
            all_results.extend(leads)

    if all_results:
        df = pd.DataFrame(all_results)
        st.success(f"Found {len(df)} results")
        st.write(df.to_markdown(index=False), unsafe_allow_html=True)

        if st.button("⬆️ Push to CRM"):
            existing_names = [row[0] for row in crm_worksheet.get_all_values()[1:]]
            new_rows = [
                [
                    r["Business Name"], "", "", r["Postcode"], "", r["Link"], "", "", r["Snippet"],
                    "", r["Scraped On"], ""
                ]
                for _, r in df.iterrows() if r["Business Name"] not in existing_names
            ]
            if new_rows:
                crm_worksheet.append_rows(new_rows)
                st.success(f"Pushed {len(new_rows)} new rows to CRM")
            else:
                st.info("No new businesses to add.")
    else:
        st.warning("No results found.")
