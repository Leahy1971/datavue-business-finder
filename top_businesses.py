import streamlit as st
import pandas as pd
import requests
from serpapi import GoogleSearch
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

# ====== CONFIGURATION ======
API_KEY = "6ba2e2001a696a5702e9a3ce0d491454f20226ff2bf0d48bb838e0562e57f847"
SHEET_URL = "https://docs.google.com/spreadsheets/d/1A0AXN6o3qrPn38XQwnkx_StTAtGQ9M97FJA-2rW3Omo/edit"
SHEET_NAME = "CRM"

def get_google_sheets_client():
    """Initialize Google Sheets client using Streamlit secrets"""
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds_dict = {
            "type": st.secrets["google_service_account"]["type"],
            "project_id": st.secrets["google_service_account"]["project_id"],
            "private_key_id": st.secrets["google_service_account"]["private_key_id"],
            "private_key": st.secrets["google_service_account"]["private_key"],
            "client_email": st.secrets["google_service_account"]["client_email"],
            "client_id": st.secrets["google_service_account"]["client_id"],
            "auth_uri": st.secrets["google_service_account"]["auth_uri"],
            "token_uri": st.secrets["google_service_account"]["token_uri"],
            "auth_provider_x509_cert_url": st.secrets["google_service_account"]["auth_provider_x509_cert_url"],
            "client_x509_cert_url": st.secrets["google_service_account"]["client_x509_cert_url"]
        }
        creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
        client = gspread.authorize(creds)
        return client.open_by_url(SHEET_URL).worksheet(SHEET_NAME)
    except Exception as e:
        st.error(f"Error connecting to Google Sheets: {e}")
        return None

def fetch_leads(postcode, query_term):
    """Fetch business leads from Google Maps via SerpAPI"""
    try:
        params = {
            "engine": "google_maps",
            "q": query_term,
            "location": postcode,
            "hl": "en",
            "type": "search",
            "api_key": API_KEY
        }
        
        search = GoogleSearch(params)
        results = search.get_dict()
        
        if "error" in results:
            st.error(f"API Error: {results['error']}")
            return []
        
        businesses = []
        for place in results.get("local_results", []):
            name = place.get("title", "")
            reviews = place.get("reviews", "")
            score = place.get("rating", "")
            link = place.get("link", "")
            address = place.get("address", "")
            phone = place.get("phone", "")
            website = place.get("website", "")
            email = place.get("email", "")
            
            # Extract number of reviews from the reviews string
            total_reviews = ""
            if isinstance(reviews, str) and "reviews" in reviews:
                total_reviews = ''.join([c for c in reviews if c.isdigit()])
            
            businesses.append({
                "Business Name": name,
                "Review Score": score,
                "Total Reviews": total_reviews,
                "Location": postcode,
                "Address": address,
                "Link": link,
                "Phone": phone,
                "Website": website,
                "Email": email,
                "Scraped On": datetime.now().strftime("%Y-%m-%d"),
                "Notes": "",
                "Reviews": reviews
            })
        
        return businesses
    
    except Exception as e:
        st.error(f"Error fetching leads: {e}")
        return []

def push_to_crm(sheet, business_data):
    """Push business data to CRM sheet"""
    try:
        if not sheet:
            st.error("Google Sheets connection not available")
            return False
            
        # Check if business already exists
        crm_data = sheet.get_all_records()
        exists = any(
            r.get("Business Name") == business_data["Business Name"] or 
            r.get("Link") == business_data["Link"]
            for r in crm_data
        )
        
        if exists:
            st.warning("⚠️ Already exists in CRM.")
            return False
        else:
            # Append new row
            sheet.append_row([
                business_data["Business Name"], 
                business_data["Review Score"], 
                business_data["Total Reviews"], 
                business_data["Location"],
                business_data["Address"], 
                business_data["Link"], 
                business_data["Phone"], 
                business_data["Website"], 
                business_data["Reviews"],
                business_data["Email"], 
                business_data["Scraped On"], 
                business_data["Notes"]
            ])
            st.success("✅ Pushed to CRM!")
            return True
    
    except Exception as e:
        st.error(f"Error pushing to CRM: {e}")
        return False

# ====== STREAMLIT UI ======
st.title("🔍 Datavue Business Finder with CRM Sync")
st.caption("Search top-rated local businesses and sync straight into your CRM Sheet")

# Initialize Google Sheets connection
sheet = get_google_sheets_client()

# Input fields
col1, col2 = st.columns(2)
query = col1.text_input("Business Type", value="plumber")
postcode = col2.text_input("Postcode", value="DA16")
radius = st.slider("Search Radius (miles)", 1, 20, 5)
open_now = st.checkbox("Open Now Only")

if st.button("Search"):
    if not query or not postcode:
        st.error("Please enter both business type and postcode")
    else:
        with st.spinner("Searching for businesses..."):
            businesses = fetch_leads(postcode, query)
        
        if not businesses:
            st.warning("No businesses found. Try a different postcode or keyword.")
        else:
            df = pd.DataFrame(businesses)
            # Sort by review score and total reviews
            df["Review Score"] = pd.to_numeric(df["Review Score"], errors='coerce')
            df["Total Reviews"] = pd.to_numeric(df["Total Reviews"], errors='coerce')
            df = df.sort_values(by=["Review Score", "Total Reviews"], ascending=False, na_position='last')
            
            st.success(f"Found {len(businesses)} businesses!")
            
            # Display results
            for i, row in df.iterrows():
                st.markdown("---")
                st.markdown(f"### 🔗 [{row['Business Name']}]({row['Link']})")
                st.write(f"📍 **Address:** {row['Address']}")
                st.write(f"⭐ **Rating:** {row['Review Score']} from {row['Total Reviews']} reviews")
                st.write(f"📞 **Phone:** {row['Phone']}")
                if row['Website']:
                    st.write(f"🌐 **Website:** [{row['Website']}]({row['Website']})")
                if row['Email']:
                    st.write(f"✉️ **Email:** {row['Email']}")
                
                # Push to CRM button
                if st.button(f"Push to CRM", key=f"push_{i}"):
                    push_to_crm(sheet, row)
            
            # Download CSV
            csv_data = df.to_csv(index=False)
            st.download_button(
                label="⬇️ Download Results as CSV",
                data=csv_data,
                file_name=f"business_results_{postcode}_{query}_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv"
            )
