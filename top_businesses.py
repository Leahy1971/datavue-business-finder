import streamlit as st
from serpapi import GoogleSearch
import pandas as pd

st.set_page_config(page_title="Local Business Finder", layout="wide")
st.title("🔍 Top 10 Local Businesses Finder")

business_type = st.text_input("Business Type", "Plumber")
postcode = st.text_input("Postcode", "DA16")
search = st.button("Search")

# Your API Key
api_key = "6ba2e2001a696a5702e9a3ce0d491454f20226ff2bf0d48bb838e0562e57f847"

if search:
    params = {
        "engine": "google_maps",
        "q": f"{business_type} in {postcode}",
        "type": "search",
        "api_key": api_key
    }

    try:
        response = GoogleSearch(params).get_dict()
        places = response.get("local_results", [])[:20]

        records = []
        for p in places:
            title = p.get("title", "N/A")
            rating = float(p.get("rating", 0))
            reviews_raw = p.get("reviews", {})
            reviews = (
                reviews_raw["total"]
                if isinstance(reviews_raw, dict) and "total" in reviews_raw
                else reviews_raw if isinstance(reviews_raw, int)
                else 0
            )
            address = p.get("address", "")
            postcode_extracted = address.split(",")[-2].strip() if "," in address else ""

            # Links
            place_id = p.get("place_id", "")
            maps_url = f"https://www.google.com/maps/place/?q=place_id:{place_id}" if place_id else ""
            website = p.get("website", "")
            email = p.get("email", "")
            phone = p.get("phone", "")

            # Markdown-formatted links
            name_md = f"[{title}]({maps_url})" if maps_url else title
            website_md = f"[Website]({website})" if website else ""
            email_md = f"[Email](mailto:{email})" if email else ""
            phone_md = f"[Call](tel:{phone})" if phone else ""

            records.append({
                "Business Name": name_md,
                "Review Score": rating,
                "Reviews": reviews,
                "Address": address,
                "Post Code": postcode_extracted,
                "Tel No": phone_md,
                "Email Address": email_md,
                "Website": website_md
            })

        df = pd.DataFrame(records)
        df = df.sort_values(by=["Review Score", "Reviews"], ascending=[False, False]).head(10)

        st.subheader("📋 Top 10 Results")
        st.markdown(df.to_markdown(index=False), unsafe_allow_html=True)

        # Clean version for download
        csv_export = df.copy()
        for col in ["Business Name", "Tel No", "Email Address", "Website"]:
            csv_export[col] = csv_export[col].str.replace(r"\[(.*?)\]\((.*?)\)", r"\1", regex=True)

        csv = csv_export.to_csv(index=False)
        st.download_button("📥 Download CSV", data=csv, file_name="top_10_businesses.csv")

    except Exception as e:
        st.error(f"❌ Search failed: {e}")
