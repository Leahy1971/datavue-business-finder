# plumber_finder_serpapi.py

import streamlit as st
from serpapi import GoogleSearch

st.title("🔍 Top-Rated Local Business Finder (Google Maps)")

business_type = st.text_input("Business Type", "Plumber")
postcode = st.text_input("Postcode", "DA16")
search = st.button("Search")

api_key =  "6ba2e2001a696a5702e9a3ce0d491454f20226ff2bf0d48bb838e0562e57f847"

if search:
    query = f"{business_type} in {postcode}"
    params = {
        "engine": "google_maps",
        "q": query,
        "type": "search",
        "api_key": api_key
    }

    try:
        search = GoogleSearch(params)
        results = search.get_dict()

        if "local_results" in results:
            for i, place in enumerate(results["local_results"][:5], 1):
                name = place.get("title", "N/A")
                rating = place.get("rating", "No rating")
                reviews = place.get("reviews", "No reviews")
                address = place.get("address", "")
                link = place.get("link", "")
                phone = place.get("phone", "")
                st.markdown(f"**{i}. [{name}]({link})**  \n⭐ {rating} ({reviews} reviews)  \n📍 {address}  \n📞 {phone}")
        else:
            st.warning("No results found.")
    except Exception as e:
        st.error(f"Error: {e}")
