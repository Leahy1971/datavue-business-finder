import streamlit as st
import pandas as pd
import requests
from serpapi import GoogleSearch
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
import time
import re
from difflib import SequenceMatcher

# ====== CONFIGURATION ======
API_KEY = "6ba2e2001a696a5702e9a3ce0d491454f20226ff2bf0d48bb838e0562e57f847"
SHEET_URL = "https://docs.google.com/spreadsheets/d/1A0AXN6o3qrPn38XQwnkx_StTAtGQ9M97FJA-2rW3Omo/edit"
SHEET_NAME = "CRM"

# Companies House API configuration
COMPANIES_HOUSE_API_KEY = st.secrets.get("companies_house_api_key", "")  # Add to your secrets
COMPANIES_HOUSE_BASE_URL = "https://api.company-information.service.gov.uk"

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
                
                # Extract turnover if available
                turnover = place.get("turnover", "") or place.get("revenue", "") or place.get("annual_sales", "")
                
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
                    "Official Name": "",  # Will be populated by Companies House
                    "Company Number": "",  # Companies House number
                    "Company Type": "",    # Ltd, PLC, etc.
                    "Review Score": score,
                    "Total Reviews": total_reviews,
                    "Location": postcode,
                    "Address": address,
                    "Link": google_maps_url,
                    "Phone": phone,
                    "Website": website,
                    "Email": email,
                    "Employee Count": employee_count,
                    "Turnover": turnover,
                    "SIC Codes": "",      # Business activity codes
                    "Incorporation Date": "",
                    "Last Accounts Date": "",
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

def similarity_score(a, b):
    """Calculate similarity between two strings"""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

def search_companies_house(business_name, postcode=None):
    """Search Companies House for matching companies"""
    
    if not COMPANIES_HOUSE_API_KEY:
        return [], "Companies House API key not configured"
    
    try:
        # Clean business name for search
        search_name = re.sub(r'\b(ltd|limited|plc|llp|&|and)\b', '', business_name.lower()).strip()
        search_name = re.sub(r'[^\w\s]', ' ', search_name).strip()
        
        # Companies House search API
        url = f"{COMPANIES_HOUSE_BASE_URL}/search/companies"
        
        # Companies House requires Basic Auth with API key as username and empty password
        import base64
        auth_string = f"{COMPANIES_HOUSE_API_KEY}:"
        auth_bytes = auth_string.encode('ascii')
        auth_b64 = base64.b64encode(auth_bytes).decode('ascii')
        
        headers = {
            'Authorization': f'Basic {auth_b64}',
            'Accept': 'application/json'
        }
        
        params = {
            'q': search_name,
            'items_per_page': 10
        }
        
        response = requests.get(url, headers=headers, params=params)
        
        if response.status_code == 401:
            return [], "Invalid Companies House API key - please check your API key is correct"
        elif response.status_code == 429:
            return [], "Rate limit exceeded - please wait a moment and try again"
        elif response.status_code != 200:
            return [], f"Companies House API error: {response.status_code} - {response.text}"
        
        data = response.json()
        companies = data.get('items', [])
        
        # Filter and score matches
        matches = []
        for company in companies:
            company_name = company.get('title', '')
            company_address = company.get('address_snippet', '')
            company_number = company.get('company_number', '')
            company_status = company.get('company_status', '')
            
            # Calculate similarity score
            name_similarity = similarity_score(business_name, company_name)
            
            # Boost score if postcode matches
            postcode_boost = 0
            if postcode and postcode.upper() in company_address.upper():
                postcode_boost = 0.2
            
            total_score = name_similarity + postcode_boost
            
            # Only include active companies with reasonable similarity
            if company_status == 'active' and total_score > 0.4:
                matches.append({
                    'company_name': company_name,
                    'company_number': company_number,
                    'address': company_address,
                    'status': company_status,
                    'similarity_score': total_score
                })
        
        # Sort by similarity score
        matches.sort(key=lambda x: x['similarity_score'], reverse=True)
        
        return matches[:3], None  # Return top 3 matches
        
    except Exception as e:
        return [], f"Error searching Companies House: {str(e)}"

def get_companies_house_financials(company_number):
    """Get financial data from Companies House"""
    
    if not COMPANIES_HOUSE_API_KEY:
        return {}, "Companies House API key not configured"
    
    try:
        # Set up Basic Auth
        import base64
        auth_string = f"{COMPANIES_HOUSE_API_KEY}:"
        auth_bytes = auth_string.encode('ascii')
        auth_b64 = base64.b64encode(auth_bytes).decode('ascii')
        
        headers = {
            'Authorization': f'Basic {auth_b64}',
            'Accept': 'application/json'
        }
        
        # Get company filing history
        url = f"{COMPANIES_HOUSE_BASE_URL}/company/{company_number}/filing-history"
        params = {
            'category': 'accounts',
            'items_per_page': 5
        }
        
        response = requests.get(url, headers=headers, params=params)
        
        if response.status_code == 401:
            return {}, "Invalid Companies House API key for financials lookup"
        elif response.status_code != 200:
            return {}, f"Filing history API error: {response.status_code}"
        
        filings_data = response.json()
        filings = filings_data.get('items', [])
        
        # Get company details for additional info
        company_url = f"{COMPANIES_HOUSE_BASE_URL}/company/{company_number}"
        company_response = requests.get(company_url, headers=headers)
        
        company_details = {}
        if company_response.status_code == 200:
            company_details = company_response.json()
        
        # Extract financial information
        financial_data = {
            'company_number': company_number,
            'official_name': company_details.get('company_name', ''),
            'incorporation_date': company_details.get('date_of_creation', ''),
            'company_type': company_details.get('type', ''),
            'sic_codes': company_details.get('sic_codes', []),
            'accounts_due': company_details.get('accounts', {}).get('next_due', ''),
            'last_accounts': company_details.get('accounts', {}).get('last_accounts', {}).get('period_end_on', ''),
            'turnover': 'Not available',
            'profit': 'Not available',
            'employees': 'Not available'
        }
        
        # Try to extract turnover from recent filings
        for filing in filings:
            if 'annual-return' not in filing.get('description', '').lower():
                filing_date = filing.get('date', '')
                if filing_date:
                    # Note: Full accounts data requires additional API calls to specific documents
                    # This would need document parsing which is complex
                    financial_data['latest_filing_date'] = filing_date
                    break
        
        return financial_data, None
        
    except Exception as e:
        return {}, f"Error getting financials: {str(e)}"

def enhance_with_companies_house(business_data):
    """Enhance business data with Companies House information"""
    
    enhanced_data = business_data.copy()
    companies_house_info = {}
    
    try:
        business_name = business_data.get('Business Name', '')
        postcode = business_data.get('Location', '')
        
        if not business_name:
            return enhanced_data, "No business name provided"
        
        # Search for matching companies
        matches, error = search_companies_house(business_name, postcode)
        
        if error:
            return enhanced_data, f"Companies House search failed: {error}"
        
        if not matches:
            return enhanced_data, "No matching companies found in Companies House"
        
        # Use the best match
        best_match = matches[0]
        company_number = best_match['company_number']
        
        # Get financial data
        financial_data, fin_error = get_companies_house_financials(company_number)
        
        if fin_error:
            companies_house_info = {
                'official_name': best_match['company_name'],
                'company_number': company_number,
                'match_score': f"{best_match['similarity_score']:.2f}",
                'error': fin_error
            }
        else:
            companies_house_info = financial_data
            companies_house_info['match_score'] = f"{best_match['similarity_score']:.2f}"
            
            # Update enhanced data with official information
            enhanced_data['Official Name'] = financial_data.get('official_name', '')
            enhanced_data['Company Number'] = company_number
            enhanced_data['Company Type'] = financial_data.get('company_type', '')
            enhanced_data['Incorporation Date'] = financial_data.get('incorporation_date', '')
            enhanced_data['SIC Codes'] = ', '.join(financial_data.get('sic_codes', [])[:3])  # First 3 SIC codes
            enhanced_data['Last Accounts Date'] = financial_data.get('last_accounts', '')
            
            # Override turnover if we have Companies House data
            if financial_data.get('turnover') and financial_data['turnover'] != 'Not available':
                enhanced_data['Turnover'] = financial_data['turnover']
        
        return enhanced_data, companies_house_info
        
    except Exception as e:
        return enhanced_data, f"Error enhancing with Companies House: {str(e)}"
    """Search the web for missing business contact information and turnover data"""
    
    import re  # Import re module at the top of the function
    
    enhanced_data = business_data.copy()
    search_results = []
    
    try:
        business_name = business_data.get('Business Name', '')
        location = business_data.get('Location', '')
        
        if not business_name:
            return enhanced_data, ["No business name provided for enhancement"]
        
        # Create search queries to find missing data
        search_queries = []
        
        # Check what data is missing and create targeted searches
        missing_phone = not business_data.get('Phone', '').strip()
        missing_email = not business_data.get('Email', '').strip()
        missing_website = not business_data.get('Website', '').strip()
        missing_turnover = not business_data.get('Turnover', '').strip()
        
        if missing_phone or missing_email or missing_website or missing_turnover:
            # Primary search - business name + location + contact
            search_queries.append(f'"{business_name}" {location} contact phone email')
            
            # Secondary search - business name + turnover/revenue
            if missing_turnover:
                search_queries.append(f'"{business_name}" {location} turnover revenue annual sales')
            
            # Tertiary search - business name + location + website
            if missing_website:
                search_queries.append(f'"{business_name}" {location} website')
            
            # Quaternary search - business name + phone number
            if missing_phone:
                search_queries.append(f'"{business_name}" {location} phone number mobile')
        
        if not search_queries:
            return enhanced_data, ["All information already available"]
        
        # Perform web searches
        for query in search_queries[:3]:  # Limit to 3 searches to avoid API limits
            params = {
                "engine": "google",
                "q": query,
                "api_key": api_key,
                "num": 5  # Limit results
            }
            
            search = GoogleSearch(params)
            results = search.get_dict()
            
            if "error" in results:
                search_results.append(f"Search error: {results['error']}")
                continue
            
            # Extract data from organic results
            organic_results = results.get("organic_results", [])
            
            if not organic_results:
                search_results.append(f"No search results found for: {query}")
                continue
            
            for result in organic_results:
                snippet = result.get("snippet", "").lower()
                title = result.get("title", "").lower()
                link = result.get("link", "")
                full_text = snippet + " " + title
                
                # Look for phone numbers in snippets
                if missing_phone:
                    # UK phone number patterns
                    phone_patterns = [
                        r'\b(?:0|\+44)\d{2,4}\s?\d{3,4}\s?\d{3,4}\b',  # UK landline/mobile
                        r'\b(?:07\d{9}|7\d{9})\b',  # UK mobile
                        r'\b0\d{3,4}\s?\d{3,4}\s?\d{3,4}\b'  # UK landline
                    ]
                    
                    for pattern in phone_patterns:
                        phone_matches = re.findall(pattern, full_text)
                        if phone_matches:
                            # Clean up the phone number
                            phone = phone_matches[0].strip()
                            if phone and len(phone) >= 10:
                                enhanced_data['Phone'] = phone
                                search_results.append(f"Found phone: {phone}")
                                missing_phone = False
                                break
                
                # Look for email addresses
                if missing_email:
                    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
                    email_matches = re.findall(email_pattern, full_text)
                    if email_matches:
                        # Filter out generic emails
                        valid_emails = [email for email in email_matches 
                                      if not any(generic in email.lower() 
                                               for generic in ['noreply', 'support', 'info@google', 'contact@example'])]
                        if valid_emails:
                            enhanced_data['Email'] = valid_emails[0]
                            search_results.append(f"Found email: {valid_emails[0]}")
                            missing_email = False
                
                # Look for turnover/revenue information
                if missing_turnover:
                    # Patterns for UK business turnover - more specific patterns
                    turnover_patterns = [
                        r'turnover[:\s]+£([\d,]+(?:\.\d+)?)\s*(million|m|k|thousand)',
                        r'revenue[:\s]+£([\d,]+(?:\.\d+)?)\s*(million|m|k|thousand)',
                        r'annual sales[:\s]+£([\d,]+(?:\.\d+)?)\s*(million|m|k|thousand)',
                        r'£([\d,]+(?:\.\d+)?)\s*(million|m)\s*turnover',
                        r'£([\d,]+(?:\.\d+)?)\s*(million|m)\s*revenue',
                        r'turnover[:\s]+£([\d,]+(?:\.\d+)?)',
                        r'revenue[:\s]+£([\d,]+(?:\.\d+)?)',
                    ]
                    
                    for pattern in turnover_patterns:
                        turnover_matches = re.findall(pattern, full_text, re.IGNORECASE)
                        if turnover_matches:
                            for match in turnover_matches:
                                if isinstance(match, tuple):
                                    # Handle patterns with scale (million, k, etc.)
                                    if len(match) >= 2:
                                        value, scale = match[0], match[1].lower()
                                    else:
                                        value, scale = match[0], ""
                                else:
                                    # Single value match
                                    value, scale = match, ""
                                
                                # Clean the value and check it's valid
                                value = value.replace(',', '').strip()
                                if value and value.replace('.', '').isdigit():
                                    # Format based on scale
                                    if 'million' in scale or scale == 'm':
                                        enhanced_data['Turnover'] = f"£{value}M"
                                    elif 'thousand' in scale or scale == 'k':
                                        enhanced_data['Turnover'] = f"£{value}K"
                                    else:
                                        # Try to guess scale based on value size
                                        float_val = float(value)
                                        if float_val >= 1000000:
                                            enhanced_data['Turnover'] = f"£{float_val/1000000:.1f}M"
                                        elif float_val >= 1000:
                                            enhanced_data['Turnover'] = f"£{float_val/1000:.0f}K"
                                        else:
                                            enhanced_data['Turnover'] = f"£{value}"
                                    
                                    search_results.append(f"Found turnover: {enhanced_data['Turnover']}")
                                    missing_turnover = False
                                    break
                            
                            if not missing_turnover:
                                break
                
                # Look for website
                if missing_website and link:
                    # Check if this link looks like a business website (not Google, Facebook, etc.)
                    exclude_domains = ['google.', 'facebook.', 'linkedin.', 'twitter.', 'instagram.', 'youtube.']
                    if not any(domain in link.lower() for domain in exclude_domains):
                        # Simple check if this might be the business website
                        business_words = business_name.lower().split()
                        if any(word in link.lower() for word in business_words if len(word) > 3):
                            enhanced_data['Website'] = link
                            search_results.append(f"Found potential website: {link}")
                            missing_website = False
        
        if not search_results:
            search_results.append("No additional information found")
        
        return enhanced_data, search_results
        
    except Exception as e:
        return enhanced_data, [f"Error during enhancement: {str(e)}"]
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
                str(business_data.get("Official Name", "")),
                str(business_data.get("Company Number", "")),
                str(business_data.get("Company Type", "")),
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
                str(business_data.get("Turnover", "")),
                str(business_data.get("SIC Codes", "")),
                str(business_data.get("Incorporation Date", "")),
                str(business_data.get("Last Accounts Date", "")),
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
    turnover_level = st.selectbox("Minimum Turnover", 
                                 ["Any", "£100K+", "£500K+", "£1M+", "£5M+", "£10M+"],
                                 help="Filter by minimum business turnover/revenue")

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
    'turnover_level': turnover_level
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
        'Business Name', 'Official Name', 'Company Number', 'Review Score', 'Total Reviews', 
        'Employee Count', 'Address', 'Phone', 'Website', 'Email', 'Turnover', 
        'Company Type', 'SIC Codes', 'Open Status', 'Link'
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
            "Official Name": st.column_config.TextColumn(
                "Official Name",
                help="Companies House registered name",
                width="medium"
            ),
            "Company Number": st.column_config.TextColumn(
                "Co. Number",
                help="Companies House registration number",
                width="small"
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
            "Turnover": st.column_config.TextColumn(
                "Turnover",
                help="Business turnover/revenue",
                width="small"
            ),
            "Company Type": st.column_config.TextColumn(
                "Type",
                help="Company type (Ltd, PLC, etc.)",
                width="small"
            ),
            "SIC Codes": st.column_config.TextColumn(
                "SIC Codes",
                help="Standard Industrial Classification codes",
                width="medium"
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
    
    # Data Enhancement Section
    st.write("**Data Enhancement:**")
    col6, col7 = st.columns([3, 2])
    
    with col6:
        # Business selector for data enhancement - fix the business_names reference
        business_names_for_enhancement = df['Business Name'].tolist()
        enhancement_business = st.selectbox(
            "Select a business to enhance contact data:",
            options=range(len(business_names_for_enhancement)),
            format_func=lambda x: f"{business_names_for_enhancement[x]} - Missing: {', '.join([item for item in [('Phone' if not df.iloc[x]['Phone'] else ''), ('Email' if not df.iloc[x]['Email'] else ''), ('Website' if not df.iloc[x]['Website'] else ''), ('Turnover' if not df.iloc[x]['Turnover'] else '')] if item])}" if x < len(business_names_for_enhancement) else "",
            key="enhancement_selector"
        )
    
    with col7:
        st.write("")  # Add some vertical space to align with selectbox
        if st.button("🔍 Enhance Contact Data", use_container_width=True):
            if enhancement_business is not None:
                selected_business_data = df.iloc[enhancement_business].to_dict()
                
                with st.spinner("🔍 Searching web for missing contact information..."):
                    enhanced_data, search_log = enhance_business_data(selected_business_data, API_KEY)
                
                # Show results
                st.write("**Enhancement Results:**")
                for log_entry in search_log:
                    if "Found" in log_entry:
                        st.success(f"✅ {log_entry}")
                    elif "Error" in log_entry:
                        st.error(f"❌ {log_entry}")
                    else:
                        st.info(f"ℹ️ {log_entry}")
                
                # Update the dataframe with enhanced data
                if enhanced_data != selected_business_data:
                    # Update the session state with enhanced data
                    for col, value in enhanced_data.items():
                        if col in df.columns:
                            st.session_state.businesses[enhancement_business][col] = value
                    
                    st.success("🎉 Business data updated! Refresh to see changes in the table.")
                    
                    # Show what was enhanced
                    st.write("**Updated Information:**")
                    changes_made = False
                    if enhanced_data.get('Phone') != selected_business_data.get('Phone'):
                        st.write(f"📞 **Phone:** {enhanced_data.get('Phone', 'Not found')}")
                        changes_made = True
                    if enhanced_data.get('Email') != selected_business_data.get('Email'):
                        st.write(f"📧 **Email:** {enhanced_data.get('Email', 'Not found')}")
                        changes_made = True
                    if enhanced_data.get('Website') != selected_business_data.get('Website'):
                        st.write(f"🌐 **Website:** {enhanced_data.get('Website', 'Not found')}")
                        changes_made = True
                    if enhanced_data.get('Turnover') != selected_business_data.get('Turnover'):
                        st.write(f"💰 **Turnover:** {enhanced_data.get('Turnover', 'Not found')}")
                        changes_made = True
                    
                    if changes_made:
                        if st.button("🔄 Refresh Results", key="refresh_after_enhancement"):
                            st.rerun()
    
    # Companies House Enhancement Section
    st.write("**Companies House Lookup:**")
    col8, col9 = st.columns([3, 2])
    
    with col8:
        # Business selector for Companies House lookup
        ch_business = st.selectbox(
            "Select a business to lookup in Companies House:",
            options=range(len(business_names_for_enhancement)),
            format_func=lambda x: f"{business_names_for_enhancement[x]} - {('✅ Already matched' if df.iloc[x]['Company Number'] else '🔍 Not matched')}" if x < len(business_names_for_enhancement) else "",
            key="companies_house_selector"
        )
    
    with col9:
        st.write("")  # Add some vertical space to align with selectbox
        if st.button("🏢 Lookup Companies House", use_container_width=True):
            if ch_business is not None:
                selected_business_data = df.iloc[ch_business].to_dict()
                
                with st.spinner("🔍 Searching Companies House records..."):
                    enhanced_data, ch_info = enhance_with_companies_house(selected_business_data)
                
                # Show results
                st.write("**Companies House Results:**")
                
                if isinstance(ch_info, str):
                    # Error message
                    st.warning(f"⚠️ {ch_info}")
                elif isinstance(ch_info, dict) and ch_info.get('error'):
                    # Partial success with error
                    st.info(f"✅ Found company match (Score: {ch_info.get('match_score', 'N/A')})")
                    st.warning(f"⚠️ {ch_info['error']}")
                    if ch_info.get('official_name'):
                        st.write(f"**Official Name:** {ch_info['official_name']}")
                    if ch_info.get('company_number'):
                        st.write(f"**Company Number:** {ch_info['company_number']}")
                else:
                    # Full success
                    st.success(f"✅ Companies House match found! (Similarity: {ch_info.get('match_score', 'N/A')})")
                    
                    # Display key information
                    col_a, col_b = st.columns(2)
                    with col_a:
                        st.write(f"**Official Name:** {ch_info.get('official_name', 'N/A')}")
                        st.write(f"**Company Number:** {ch_info.get('company_number', 'N/A')}")
                        st.write(f"**Company Type:** {ch_info.get('company_type', 'N/A')}")
                        st.write(f"**Incorporation:** {ch_info.get('incorporation_date', 'N/A')}")
                    
                    with col_b:
                        st.write(f"**SIC Codes:** {', '.join(ch_info.get('sic_codes', [])[:3])}")
                        st.write(f"**Last Accounts:** {ch_info.get('last_accounts', 'N/A')}")
                        st.write(f"**Accounts Due:** {ch_info.get('accounts_due', 'N/A')}")
                        if ch_info.get('latest_filing_date'):
                            st.write(f"**Latest Filing:** {ch_info['latest_filing_date']}")
                
                # Update the dataframe with enhanced data
                if enhanced_data != selected_business_data:
                    # Update the session state with enhanced data
                    for col, value in enhanced_data.items():
                        if col in df.columns:
                            st.session_state.businesses[ch_business][col] = value
                    
                    st.success("🎉 Business data updated with Companies House information!")
                    
                    if st.button("🔄 Refresh Results", key="refresh_after_ch_lookup"):
                        st.rerun()
    
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
