import streamlit as st
import pandas as pd
import requests
from serpapi import GoogleSearch
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
import time

# ====== CONFIGURATION ======
API_KEY = "6ba2e2001a696a5702e9a3ce0d491454f20226ff2bf0d48bb838e0562e57f847"
SHEET_URL = "https://docs.google.com/spreadsheets/d/1A0AXN6o3qrPn38XQwnkx_StTAtGQ9M97FJA-2rW3Omo/edit"
SHEET_NAME = "CRM"

# Initialize session state
if 'businesses' not in st.session_state:
    st.session_state.businesses = []
if 'search_performed' not in st.session_state:
    st.session_state.search_performed = False

def get_google_sheets_client():
    """Initialize Google Sheets client using Streamlit secrets"""
    # Check if secrets are available
    if "google_service_account" not in st.secrets:
        st.error("❌ Google service account credentials not found in secrets")
        st.info("Please add your Google service account JSON to Streamlit secrets")
        return None
    
    st.write("✅ Found Google service account credentials")
    
    # Check required fields
    required_fields = ["type", "project_id", "private_key", "client_email"]
    missing_fields = []
    
    for field in required_fields:
        if field not in st.secrets["google_service_account"]:
            missing_fields.append(field)
    
    if missing_fields:
        st.error(f"❌ Missing required fields in Google service account: {missing_fields}")
        return None
        
    st.write("✅ All required credential fields present")
    
    # Create credentials
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
    
    try:
        st.write("🔑 Creating credentials...")
        creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
        
        st.write("🔗 Authorizing with Google...")
        google_client = gspread.authorize(creds)
        
        st.write("📊 Opening spreadsheet...")
        spreadsheet = google_client.open_by_url(SHEET_URL)
        
        st.write("📋 Accessing worksheet...")
        sheet = spreadsheet.worksheet(SHEET_NAME)
        
        st.success("✅ Successfully connected to Google Sheets!")
        return sheet
        
    except gspread.WorksheetNotFound:
        st.error(f"❌ Worksheet '{SHEET_NAME}' not found.")
        try:
            worksheets = [ws.title for ws in spreadsheet.worksheets()]
            st.write(f"Available worksheets: {worksheets}")
        except:
            st.error("Could not list available worksheets")
        return None
        
    except Exception as e:
        st.error(f"❌ Error: {str(e)}")
        st.error(f"❌ Error type: {type(e).__name__}")
        
        # More specific error handling
        if "private_key" in str(e):
            st.error("🔑 Issue with private key - check if it's properly formatted")
        elif "client_email" in str(e):
            st.error("📧 Issue with client email - check service account email")
        elif "permission" in str(e).lower():
            st.error("🔐 Permission issue - make sure service account has access to the sheet")
        elif "not found" in str(e).lower():
            st.error("📄 Spreadsheet not found - check the URL")
            
        return None

def fetch_leads(postcode, query_term):
    """Fetch business leads from Google Maps via SerpAPI"""
    try:
        # Format location for UK postcodes to improve search accuracy
        location = f"{postcode}, UK"
        search_query = f"{query_term} near {postcode}, UK"
        
        params = {
            "engine": "google_maps",
            "q": search_query,
            "location": location,
            "hl": "en",
            "gl": "uk",  # Country code for UK
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
            # Use gps_coordinates to construct proper Google Maps URL
            gps = place.get("gps_coordinates", {})
            place_id = place.get("place_id", "")
            
            # Construct Google Maps URL that goes to reviews
            if place_id:
                # Use place_id for most accurate link to reviews
                google_maps_url = f"https://www.google.com/maps/place/?q=place_id:{place_id}"
            elif gps.get("latitude") and gps.get("longitude"):
                # Fallback to coordinates
                lat = gps["latitude"]
                lng = gps["longitude"]
                google_maps_url = f"https://www.google.com/maps/place/{lat},{lng}"
            else:
                # Final fallback to search URL
                google_maps_url = place.get("link", "")
            
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
                "Link": google_maps_url,
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
    if not sheet:
        st.error("❌ Google Sheets connection not available")
        return False
    
    try:
        with st.spinner("Checking if business exists in CRM..."):
            # Check if business already exists
            crm_data = sheet.get_all_records()
            st.info(f"Found {len(crm_data)} existing records in CRM")
            
            # Check for duplicates
            business_name = str(business_data.get("Business Name", "")).strip().lower()
            business_link = str(business_data.get("Link", "")).strip()
            
            exists = any(
                str(r.get("Business Name", "")).strip().lower() == business_name or 
                str(r.get("Link", "")).strip() == business_link
                for r in crm_data
            )
            
            if exists:
                st.warning("⚠️ Business already exists in CRM.")
                return False
            
        with st.spinner("Adding business to CRM..."):
            # Prepare data for insertion - ensure all values are strings
            row_data = [
                str(business_data.get("Business Name", "")),
                str(business_data.get("Review Score", "")),
                str(business_data.get("Total Reviews", "")),
                str(business_data.get("Location", "")),
                str(business_data.get("Address", "")),
                str(business_data.get("Link", "")),
                str(business_data.get("Phone", "")),
                str(business_data.get("Website", "")),
                str(business_data.get("Reviews", "")),
                str(business_data.get("Email", "")),
                str(business_data.get("Scraped On", "")),
                str(business_data.get("Notes", ""))
            ]
            
            # Append new row
            sheet.append_row(row_data)
            st.success("✅ Successfully pushed to CRM!")
            
            # Add a small delay to ensure the data is written
            time.sleep(1)
            
            return True
    
    except Exception as e:
        st.error(f"❌ Error pushing to CRM: {str(e)}")
        st.error("Please check your Google Sheets permissions and connection")
        return False

# ====== STREAMLIT UI ======
st.title("🔍 Datavue Business Finder with CRM Sync")
st.caption("Search top-rated local businesses and sync straight into your CRM Sheet")

# Initialize Google Sheets connection
with st.spinner("Connecting to Google Sheets..."):
    sheet = get_google_sheets_client()

if sheet:
    st.success("🔗 Google Sheets connected successfully!")
else:
    st.error("❌ Google Sheets connection failed. CRM features will be disabled.")
    st.info("💡 Make sure your Google service account credentials are properly configured in Streamlit secrets.")

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
            st.session_state.businesses = businesses
            st.session_state.search_performed = True
        
        if not businesses:
            st.warning("No businesses found. Try a different postcode or keyword.")
        else:
            st.success(f"Found {len(businesses)} businesses!")

# Display results from session state
if st.session_state.search_performed and st.session_state.businesses:
    df = pd.DataFrame(st.session_state.businesses)
    # Sort by review score and total reviews
    df["Review Score"] = pd.to_numeric(df["Review Score"], errors='coerce')
    df["Total Reviews"] = pd.to_numeric(df["Total Reviews"], errors='coerce')
    df = df.sort_values(by=["Review Score", "Total Reviews"], ascending=False, na_position='last')
    
    st.write("---")
    st.subheader("Search Results")
    
    # Create a display dataframe for the table
    display_df = df.copy()
    
    # Select and reorder columns for display
    display_columns = [
        'Business Name', 'Review Score', 'Total Reviews', 'Address', 
        'Phone', 'Website', 'Email', 'Link'
    ]
    
    # Display the table with proper link configuration
    st.dataframe(
        display_df[display_columns],
        use_container_width=True,
        hide_index=True,
        column_config={
            "Business Name": st.column_config.TextColumn(
                "Business Name",
                width="medium"
            ),
            "Review Score": st.column_config.NumberColumn(
                "Rating",
                help="Google rating out of 5",
                width="small",
                format="%.1f"
            ),
            "Total Reviews": st.column_config.NumberColumn(
                "Reviews",
                help="Number of reviews",
                width="small"
            ),
            "Address": st.column_config.TextColumn(
                "Address",
                width="large"
            ),
            "Phone": st.column_config.TextColumn(
                "Phone",
                width="medium"
            ),
            "Website": st.column_config.LinkColumn(
                "Website",
                help="Business website",
                width="medium"
            ),
            "Email": st.column_config.TextColumn(
                "Email",
                width="medium"
            ),
            "Link": st.column_config.LinkColumn(
                "Google Maps",
                help="View on Google Maps",
                width="medium"
            )
        },
        height=600
    )
    
    st.write("---")
    st.subheader("CRM Actions")
    
    # Add CRM push buttons below the table
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("🔄 Push All to CRM"):
            if sheet:
                success_count = 0
                for _, row in df.iterrows():
                    if push_to_crm(sheet, row):
                        success_count += 1
                
                if success_count > 0:
                    st.success(f"✅ Successfully pushed {success_count} businesses to CRM!")
                else:
                    st.warning("⚠️ No new businesses were added (all may already exist)")
            else:
                st.error("❌ CRM unavailable - Google Sheets not connected")
    
    with col2:
        # Individual business selector for CRM push
        business_names = df['Business Name'].tolist()
        selected_business = st.selectbox(
            "Select business to push to CRM:",
            options=range(len(business_names)),
            format_func=lambda x: business_names[x] if x < len(business_names) else "",
            key="business_selector"
        )
    
    with col3:
        if st.button("📤 Push Selected to CRM"):
            if sheet and selected_business is not None:
                selected_row = df.iloc[selected_business]
                success = push_to_crm(sheet, selected_row)
                if success:
                    st.rerun()
            else:
                st.error("❌ CRM unavailable - Google Sheets not connected")
    
    # Download CSV
    csv_data = df.to_csv(index=False)
    st.download_button(
        label="⬇️ Download Results as CSV",
        data=csv_data,
        file_name=f"business_results_{postcode}_{query}_{datetime.now().strftime('%Y%m%d')}.csv",
        mime="text/csv"
    )
