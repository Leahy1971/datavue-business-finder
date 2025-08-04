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

def apply_filters(businesses, filters):
    """Apply additional filters to the businesses list"""
    filtered_businesses = []
    
    for business in businesses:
        # Rating filter
        if filters.get('min_rating', 0) > 0:
            rating = business.get('Review Score', 0)
            if rating and float(rating) < filters['min_rating']:
                continue
        
        # Minimum reviews filter
        if filters.get('min_reviews', 0) > 0:
            reviews = business.get('Total Reviews', '0')
            if reviews and int(reviews.replace(',', '')) < filters['min_reviews']:
                continue
        
        # Employee count filter
        if filters.get('min_employees') and filters['min_employees'] != "Any":
            employee_count = business.get('Employee Count', 0)
            if employee_count:
                try:
                    emp_count = int(employee_count)
                    if filters['min_employees'] == "10+" and emp_count < 10:
                        continue
                    elif filters['min_employees'] == "50+" and emp_count < 50:
                        continue
                    elif filters['min_employees'] == "100+" and emp_count < 100:
                        continue
                except (ValueError, TypeError):
                    # If employee count is not a valid number, exclude if filter is set
                    if filters['min_employees'] != "Any":
                        continue
        
        # Phone number requirement
        if filters.get('require_phone', False):
            if not business.get('Phone', '').strip():
                continue
        
        # Website requirement
        if filters.get('require_website', False):
            if not business.get('Website', '').strip():
                continue
        
        # Email requirement
        if filters.get('require_email', False):
            if not business.get('Email', '').strip():
                continue
        
        # Exclude keywords in business name
        if filters.get('exclude_keywords', ''):
            name_lower = business.get('Business Name', '').lower()
            exclude_list = [kw.strip().lower() for kw in filters['exclude_keywords'].split(',')]
            if any(kw in name_lower for kw in exclude_list if kw):
                continue
        
        # Include only keywords in business name
        if filters.get('include_keywords', ''):
            name_lower = business.get('Business Name', '').lower()
            include_list = [kw.strip().lower() for kw in filters['include_keywords'].split(',')]
            if not any(kw in name_lower for kw in include_list if kw):
                continue
        
        filtered_businesses.append(business)
    
    return filtered_businesses

def build_search_query(query_term, postcode, filters):
    """Build enhanced search query with additional criteria"""
    base_query = f"{query_term} near {postcode}, UK"
    
    # Add qualifiers based on filters
    query_modifiers = []
    
    if filters.get('open_now', False):
        query_modifiers.append("open now")
    
    if filters.get('price_level') and filters['price_level'] != "Any":
        price_map = {
            "Budget ($)": "cheap affordable budget",
            "Moderate ($$)": "moderate pricing",
            "Expensive ($$$)": "premium high-end",
            "Very Expensive ($$$$)": "luxury expensive"
        }
        if filters['price_level'] in price_map:
            query_modifiers.append(price_map[filters['price_level']])
    
    # Add employee size qualifiers to help find larger companies
    if filters.get('min_employees') and filters['min_employees'] != "Any":
        size_map = {
            "10+": "company established business",
            "50+": "large company corporation established",
            "100+": "corporation large company enterprise"
        }
        if filters['min_employees'] in size_map:
            query_modifiers.append(size_map[filters['min_employees']])
    
    # Add modifiers to query
    if query_modifiers:
        base_query += " " + " ".join(query_modifiers)
    
    return base_query

def fetch_leads(postcode, query_term, search_filters):
    """Fetch business leads from Google Maps via SerpAPI with enhanced search"""
    
    all_businesses = []
    
    try:
        location = f"{postcode}, UK"
        search_query = build_search_query(query_term, postcode, search_filters)
        max_results_requested = search_filters.get('max_results', 20)
        
        seen_business_names = set()
        seen_place_ids = set()
        
        # Create search queries
        search_queries = [search_query]  # Always start with the base query
        
        if max_results_requested > 20:
            # Add more search variations for higher result counts
            additional_queries = [
                f"{query_term} services near {postcode}, UK",
                f"{query_term} company near {postcode}, UK",
                f"best {query_term} near {postcode}, UK",
                f"top {query_term} near {postcode}, UK",
                f"{query_term} business near {postcode}, UK",
            ]
            
            # Add variations until we have enough search queries
            variations_needed = min(5, (max_results_requested + 15) // 16)
            search_queries.extend(additional_queries[:variations_needed])
        
        st.info(f"🔍 Fetching {max_results_requested} results using {len(search_queries)} search queries")
        
        # Show progress for multiple queries
        if len(search_queries) > 1:
            progress_bar = st.progress(0)
        
        # Execute each search query
        for query_index, current_query in enumerate(search_queries):
            
            if len(search_queries) > 1:
                progress_bar.progress(query_index / len(search_queries))
            
            # API call parameters
            params = {
                "engine": "google_maps",
                "q": current_query,
                "location": location,
                "hl": "en",
                "gl": "uk",
                "type": "search",
                "api_key": API_KEY
            }
            
            if search_filters.get('open_now', False):
                params["ludocid"] = None
            
            # Make the API call
            search = GoogleSearch(params)
            results = search.get_dict()
            
            # Check for errors
            if "error" in results:
                error_message = f"API Error on query {query_index + 1}: {results['error']}"
                if query_index == 0:
                    st.error(error_message)
                    return []
                else:
                    st.warning(error_message + " - Continuing...")
                    continue
            
            # Get local results
            local_results = results.get("local_results", [])
            if not local_results:
                if query_index == 0:
                    st.warning("No businesses found matching your criteria.")
                continue
            
            # Process each business result
            for place in local_results:
                name = place.get("title", "")
                place_id = place.get("place_id", "")
                
                # Skip duplicates
                if name.lower() in seen_business_names or place_id in seen_place_ids:
                    continue
                
                # Track this business
                if name:
                    seen_business_names.add(name.lower())
                if place_id:
                    seen_place_ids.add(place_id)
                
                # Extract business information
                reviews = place.get("reviews", "")
                score = place.get("rating", "")
                gps = place.get("gps_coordinates", {})
                address = place.get("address", "")
                phone = place.get("phone", "")
                website = place.get("website", "")
                price_level = place.get("price", "")
                hours = place.get("hours", "")
                is_open = place.get("open_state", "")
                
                # Build Google Maps URL
                if place_id:
                    google_maps_url = f"https://www.google.com/maps/place/?q=place_id:{place_id}"
                elif gps.get("latitude") and gps.get("longitude"):
                    lat = gps["latitude"]
                    lng = gps["longitude"]
                    google_maps_url = f"https://www.google.com/maps/place/{lat},{lng}"
                else:
                    google_maps_url = place.get("link", "")
                
                # Extract employee count
                employee_count = place.get("employees", "") or place.get("company_size", "")
                
                # Extract email
                email = place.get("email", "") or place.get("contact_info", {}).get("email", "")
                
                # Extract review count
                total_reviews = ""
                if reviews:
                    if isinstance(reviews, str):
                        import re
                        numbers = re.findall(r'\d+', reviews)
                        if numbers:
                            total_reviews = numbers[0]
                    else:
                        total_reviews = str(reviews)
                
                if not total_reviews:
                    total_reviews = str(place.get("reviews_count", "") or place.get("user_ratings_total", "") or "0")
                
                # Create business record
                business = {
                    "Business Name": name,
                    "Review Score": score,
                    "Total Reviews": total_reviews,
                    "Location": postcode,
                    "Address": address,
                    "Link": google_maps_url,
                    "Phone": phone,
                    "Website": website,
                    "Email": email,
                    "Employee Count": employee_count,
                    "Price Level": price_level,
                    "Hours": hours,
                    "Open Status": is_open,
                    "Scraped On": datetime.now().strftime("%Y-%m-%d"),
                    "Notes": "",
                    "Reviews": reviews
                }
                
                all_businesses.append(business)
                
                # Stop if we have enough results
                if len(all_businesses) >= max_results_requested:
                    break
            
            # Stop outer loop if we have enough results
            if len(all_businesses) >= max_results_requested:
                break
            
            # Small delay between API calls
            if query_index < len(search_queries) - 1:
                time.sleep(0.5)
        
        # Complete progress bar
        if len(search_queries) > 1:
            progress_bar.progress(1.0)
        
        # Show results summary
        if all_businesses:
            st.success(f"✅ Collected {len(all_businesses)} unique businesses from {query_index + 1} search queries")
        else:
            st.warning("No businesses found with current criteria.")
        
        # Apply filters
        filtered_businesses = apply_filters(all_businesses, search_filters)
        
        # Sort by quality
        def get_sort_key(business):
            try:
                rating = float(business.get('Review Score', 0) or 0)
            except:
                rating = 0
            
            try:
                review_count = int(str(business.get('Total Reviews', '0')).replace(',', '') or 0)
            except:
                review_count = 0
            
            return (-rating, -review_count)
        
        filtered_businesses.sort(key=get_sort_key)
        
        # Limit final results
        if max_results_requested > 0:
            filtered_businesses = filtered_businesses[:max_results_requested]
        
        return filtered_businesses
        
    except Exception as e:
        st.error(f"Error in fetch_leads: {str(e)}")
        return all_businesses

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
                str(business_data.get("Employee Count", "")),
                str(business_data.get("Price Level", "")),
                str(business_data.get("Hours", "")),
                str(business_data.get("Open Status", "")),
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
st.title("🔍 Enhanced Datavue Business Finder with CRM Sync")
st.caption("Search top-rated local businesses with advanced filtering and sync straight into your CRM Sheet")

# Initialize Google Sheets connection
with st.spinner("Connecting to Google Sheets..."):
    sheet = get_google_sheets_client()

if sheet:
    st.success("🔗 Google Sheets connected successfully!")
else:
    st.error("❌ Google Sheets connection failed. CRM features will be disabled.")
    st.info("💡 Make sure your Google service account credentials are properly configured in Streamlit secrets.")

# Enhanced Input Section
st.subheader("🎯 Search Parameters")

# Basic search fields
col1, col2 = st.columns(2)
query = col1.text_input("Business Type", value="plumber", help="e.g., plumber, restaurant, dentist")
postcode = col2.text_input("Postcode", value="DA16", help="UK postcode for location-based search")

# Search radius and open now
col3, col4 = st.columns(2)
radius = col3.slider("Search Radius (miles)", 1, 20, 5)
open_now = col4.checkbox("Open Now Only", help="Only show businesses currently open")

# Results quantity selector
max_results = st.selectbox(
    "Number of Results (Top Reviewed)",
    options=[5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100],
    index=2,  # Default to 20
    help="Select how many top-reviewed businesses to return (sorted by rating and review count)"
)

# Advanced Filters Section
with st.expander("🔧 Advanced Filters", expanded=False):
    st.subheader("Quality Filters")
    
    col1, col2 = st.columns(2)
    min_rating = col1.slider("Minimum Rating", 0.0, 5.0, 0.0, 0.1, 
                            help="Filter businesses with rating below this threshold")
    min_reviews = col2.number_input("Minimum Reviews", min_value=0, value=0, 
                                   help="Filter businesses with fewer reviews than this")
    
    st.subheader("Contact Information Requirements")
    col3, col4, col5 = st.columns(3)
    require_phone = col3.checkbox("Must have Phone", help="Only show businesses with phone numbers")
    require_website = col4.checkbox("Must have Website", help="Only show businesses with websites")
    require_email = col5.checkbox("Must have Email", help="Only show businesses with email addresses")
    
    st.subheader("Business Name Filters")
    col6, col7 = st.columns(2)
    include_keywords = col6.text_input("Include Keywords", 
                                      help="Comma-separated keywords that MUST be in business name")
    exclude_keywords = col7.text_input("Exclude Keywords", 
                                      help="Comma-separated keywords to EXCLUDE from business name")
    
    st.subheader("Company Size Filter")
    min_employees = st.selectbox("Minimum Employee Count", 
                                ["Any", "10+", "50+", "100+"],
                                help="Filter by minimum company size (employee count)")
    
    st.subheader("Additional Criteria")
    price_level = st.selectbox("Price Level", 
                              ["Any", "Budget ($)", "Moderate ($$)", "Expensive ($$$)", "Very Expensive ($$$$)"],
                              help="Filter by business price level")

# Compile filters into dictionary
search_filters = {
    'open_now': open_now,
    'max_results': max_results,
    'min_rating': min_rating,
    'min_reviews': min_reviews,
    'min_employees': min_employees,
    'require_phone': require_phone,
    'require_website': require_website,
    'require_email': require_email,
    'include_keywords': include_keywords,
    'exclude_keywords': exclude_keywords,
    'price_level': price_level
}

# Search button with enhanced functionality
if st.button("🔍 Search with Filters", type="primary"):
    if not query or not postcode:
        st.error("Please enter both business type and postcode")
    else:
        with st.spinner("Searching for businesses with your filters..."):
            businesses = fetch_leads(postcode, query, search_filters)
            st.session_state.businesses = businesses
            st.session_state.search_performed = True
        
        if not businesses:
            st.warning("No businesses found matching your criteria. Try adjusting your filters.")
        else:
            st.success(f"Found {len(businesses)} businesses matching your criteria!")

# Display results from session state
if st.session_state.search_performed and st.session_state.businesses:
    df = pd.DataFrame(st.session_state.businesses)
    # Data is already sorted by the fetch_leads function, so we don't need to sort again
    # Convert to numeric for display purposes
    df["Review Score"] = pd.to_numeric(df["Review Score"], errors='coerce')
    df["Total Reviews"] = pd.to_numeric(df["Total Reviews"], errors='coerce')
    
    st.write("---")
    
    # Results summary
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Results Returned", len(df))
    with col2:
        avg_rating = df["Review Score"].mean() if not df["Review Score"].isna().all() else 0
        st.metric("Average Rating", f"{avg_rating:.1f}")
    with col3:
        businesses_with_phone = len(df[df["Phone"].str.strip() != ""])
        st.metric("With Phone", businesses_with_phone)
    with col4:
        businesses_with_website = len(df[df["Website"].str.strip() != ""])
        st.metric("With Website", businesses_with_website)
    
    # Quality indicator
    top_rated = len(df[df["Review Score"] >= 4.0]) if not df["Review Score"].isna().all() else 0
    if top_rated > 0:
        st.info(f"⭐ {top_rated} businesses with 4+ star ratings in your results")
    
    st.subheader("📊 Search Results")
    
    # Create a display dataframe for the table
    display_df = df.copy()
    
    # Select and reorder columns for display
    display_columns = [
        'Business Name', 'Review Score', 'Total Reviews', 'Employee Count', 
        'Address', 'Phone', 'Website', 'Email', 'Price Level', 'Open Status', 'Link'
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
            "Employee Count": st.column_config.TextColumn(
                "Employees",
                help="Estimated employee count",
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
            "Price Level": st.column_config.TextColumn(
                "Price",
                width="small"
            ),
            "Open Status": st.column_config.TextColumn(
                "Status",
                width="small"
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
    st.subheader("📝 CRM Actions")
    
    # Redesigned CRM Actions with better visual layout
    
    # Top row - Push all and download actions
    col1, col2, col3 = st.columns([2, 1, 2])
    
    with col1:
        if st.button("🔄 Push All to CRM", use_container_width=True, type="primary"):
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
        st.write("")  # Empty middle column for spacing
    
    with col3:
        # Download CSV
        csv_data = df.to_csv(index=False)
        st.download_button(
            label="⬇️ Download Results as CSV",
            data=csv_data,
            file_name=f"filtered_business_results_{postcode}_{query}_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
            use_container_width=True
        )
    
    st.write("")  # Add some vertical spacing
    
    # Bottom row - Individual business selection
    st.write("**Individual Business Actions:**")
    col4, col5 = st.columns([3, 2])
    
    with col4:
        # Individual business selector for CRM push
        business_names = df['Business Name'].tolist()
        selected_business = st.selectbox(
            "Select a business to push to CRM:",
            options=range(len(business_names)),
            format_func=lambda x: business_names[x] if x < len(business_names) else "",
            key="business_selector"
        )
    
    with col5:
        st.write("")  # Add some vertical space to align with selectbox
        if st.button("📤 Push Selected to CRM", use_container_width=True):
            if sheet and selected_business is not None:
                selected_row = df.iloc[selected_business]
                success = push_to_crm(sheet, selected_row)
                if success:
                    st.rerun()
            else:
                st.error("❌ CRM unavailable - Google Sheets not connected")
