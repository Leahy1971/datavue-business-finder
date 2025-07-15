# plumber_finder_app.py

import streamlit as st
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus
from fake_useragent import UserAgent

st.title("🔍 Top-Rated Local Business Finder")

business_type = st.text_input("Business Type (e.g. Plumber)", "Plumber")
postcode = st.text_input("Postcode (e.g. DA16)", "DA16")
search = st.button("Search Google Maps")

if search:
    query = f"{business_type} in {postcode}"
    url = f"https://www.google.com/search?q={quote_plus(query)}&tbm=lcl"

    headers = {"User-Agent": UserAgent().random}
    response = requests.get(url, headers=headers)
    soup = BeautifulSoup(response.text, "html.parser")

    results = soup.select('.VkpGBb')[:5]

    if results:
        for i, result in enumerate(results, 1):
            name = result.select_one('.dbg0pd').get_text(strip=True) if result.select_one('.dbg0pd') else "N/A"
            rating = result.select_one('.BTtC6e').get_text(strip=True) if result.select_one('.BTtC6e') else "No rating"
            address = result.select_one('.rllt__details div').get_text(strip=True) if result.select_one('.rllt__details div') else ""
            st.markdown(f"**{i}. {name}**  \n⭐ {rating}  \n📍 {address}")
    else:
        st.warning("No results found or Google blocked the request.")
