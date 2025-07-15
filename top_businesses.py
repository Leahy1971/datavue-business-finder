import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus
from datetime import datetime
import gspread
from google.oauth2 import service_account

# ✅ Load secrets
st.write("✅ Loaded secrets:", list(st.secrets.keys()))

# ✅ Google Sheets setup
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = service_account.Credentials.from_service_account_info(
    st.secrets["google_service_account"], scopes=scope
)
client = gspread.authorize(creds)
sheet = client.open_by_url("https://docs.google.com/spreadsheets/d/1A0AXN6o3qrPn38XQwnkx_StTAtGQ9M97FJA-2rW3Omo/edit")
crm_worksheet = sheet.worksheet("CRM")

# ✅ Streamlit UI
st.set_page_config(page_title="Local Business Finder", layout="wide")
st.title("🔎 Datavue Business Finder")
postcode = st.text_input("Enter postcode", "DA16")
keywords = st.text_input("Search keywords (comma-separated)", "plumber, electrician, locksmith")
radius = st.slider("Search radius (miles)", 1, 20, 5)
search_button = st.button("Search")

@st.cache_data(show_spinner=False)
def fetch_leads(postcode, keyword):
    url = f"https://www.google.com/search?q={quote_plus(keyword + ' near ' + postcode)}"
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(url, headers=headers)
    soup = BeautifulSoup(response.text, "html.parser")
    results = []
    for g in soup.select(".tF2Cxc"):
        title = g.select_one("h3")
        link = g.select_one(".yuRUbf a")["href"] if g.select_one(".yuRUbf a") else ""
        snippet = g.select_one(".VwiC3b")
        if title and link:
            results.append({
                "Business Name": f"[{title.text}]({link})",
                "Link": link,
                "Snippet": snippet.text if snippet else "",
                "Keyword": keyword,
                "Postcode": postcode,
                "Scraped On": datetime.now().strftime("%Y-%m-%d %H:%M")
            })
    return results

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

        st.markdown("### Results")
        st.write(df.to_markdown(index=False), unsafe_allow_html=True)

        if st.button("⬆️ Push to CRM"):
            existing_names = [row[0] for row in crm_worksheet.get_all_values()[1:]]
            new_rows = []
            for _, r in df.iterrows():
                name_text = BeautifulSoup(r["Business Name"], "html.parser").text
                if name_text not in existing_names:
                    new_rows.append([
                        name_text, "", "", r["Postcode"], "", r["Link"], "", "", r["Snippet"],
                        "", r["Scraped On"], ""
                    ])
            if new_rows:
                crm_worksheet.append_rows(new_rows)
                st.success(f"Pushed {len(new_rows)} new rows to CRM")
            else:
                st.info("No new businesses to add.")
    else:
        st.warning("No results found.")
