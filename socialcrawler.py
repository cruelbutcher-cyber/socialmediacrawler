#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Streamlit Enhanced Social Media Link Scanner
Find keywords in outgoing links from any public X/Twitter profile
"""

import streamlit as st
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import re
import time
import hashlib
import csv
from io import StringIO
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

# --------------------------- Page Config ---------------------------
st.set_page_config(
    page_title="Social Media Link Scanner",
    page_icon="magnifying_glass",
    layout="wide"
)

st.title("Social Media Outgoing Link Scanner")
st.markdown("""
Search **all links** shared in a public X/Twitter profile (including replies and quote tweets)  
for your target keywords — even inside shortened, affiliate, or redirected URLs.
""")

# --------------------------- Crawler Class ---------------------------
class SocialMediaCrawler:
    def __init__(self, profile_url, keywords):
        self.profile_url = profile_url.rstrip("/")
        self.keywords = [k.strip().lower() for k in keywords if k.strip()]
        self.results = []
        self.visited = set()
        self.redirect_cache = {}
        self.url_checked = set()

        self.shorteners = {
            'bit.ly', 'tinyurl.com', 't.co', 'goo.gl', 'ow.ly', 'is.gd',
            'buff.ly', 'adf.ly', 'bit.do', 'mcaf.ee', 'tiny.cc'
        }

    def is_likely_affiliate(self, url):
        url_l = url.lower()
        parsed = urlparse(url_l)
        netloc = parsed.netloc
        if any(s in netloc for s in self.shorteners):
            return True
        if netloc.startswith(('track.', 'go.', 'click.', 'ref.', 'link.', 'out.')):
            return True
        if 'awin1.com' in netloc or 'zenaps.com' in netloc:
            return True
        return False

    def resolve_redirect(self, url):
        if url in self.redirect_cache:
            return self.redirect_cache[url]
        try:
            resp = requests.head(url, allow_redirects=True, timeout=8, headers={
                "User-Agent": "Mozilla/5.0"
            })
            final = resp.url
        except:
            final = url
        self.redirect_cache[url] = final
        return final

    def match_keywords(self, text):
        if not text:
            return []
        return [kw for kw in self.keywords if kw in text.lower()]

    def add_result(self, source_url, matched_url, location_type, context=""):
        matched = self.match_keywords(matched_url)
        if matched:
            self.results.append({
                "source_url": source_url,
                "matched_url": matched_url,
                "keyword": ", ".join(matched),
                "location_type": location_type,
                "context": context[:200],
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })

    def extract_and_check_links(self, html, base_url):
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"].split("#")[0].split("?")[0]  # clean
            full_url = urljoin(base_url, href)
            if full_url in self.url_checked:
                continue
            self.url_checked.add(full_url)

            # 1. Direct match
            self.add_result(base_url, full_url, "direct_url", a.get_text(strip=True))

            # 2. Suspected redirect → resolve and check final URL
            if self.is_likely_affiliate(full_url):
                final_url = self.resolve_redirect(full_url)
                if final_url != full_url:
                    self.add_result(base_url, final_url, "redirected_url",
                                    f"Shortened → {final_url}")

    def crawl(self):
        # Launch headless browser
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64)")

        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        driver.get(self.profile_url)

        st.info("Scrolling timeline to load all posts... (up to 2 minutes)")
        scroll_pause = 2.5
        last_height = driver.execute_script("return document.body.scrollHeight")

        for i in range(40):  # ~100 seconds max
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(scroll_pause)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height

        html = driver.page_source
        driver.quit()

        # Extract all tweet URLs
        tweet_urls = set(re.findall(r'https?://(?:x\.com|twitter\.com)/\w+/status/\d+', html))
        st.write(f"Found **{len(tweet_urls)}** tweets. Analyzing links...")

        # Analyze main profile page
        self.extract_and_check_links(html, self.profile_url)

        # Analyze each individual tweet
        for tweet_url in tweet_urls:
            if tweet_url in self.visited:
                continue
            self.visited.add(tweet_url)
            try:
                resp = requests.get(tweet_url, timeout=12)
                if resp.status_code == 200:
                    self.extract_and_check_links(resp.text, tweet_url)
            except:
                continue

        return self.results

# --------------------------- Streamlit Interface ---------------------------
with st.sidebar:
    st.header("Configuration")
    profile_url = st.text_input(
        "Profile URL (public only)",
        placeholder="https://x.com/elonmusk",
        help="Works on x.com or twitter.com profiles"
    )

    keywords_input = st.text_area(
        "Keywords to find (one per line)",
        value="gowithguide\ngo with guide\ngo-with-guide",
        height=120,
        help="Case-insensitive search in final URLs"
    )

    start_button = st.button("Start Scanning", type="primary")  # ← Fixed line!

if start_button:
    if not profile_url.strip():
        st.error("Please enter a profile URL")
    elif not keywords_input.strip():
        st.error("Please enter at least one keyword")
    else:
        with st.status("Crawling in progress...", expanded=True) as status:
            st.write("Launching browser...")
            keywords = [line.strip() for line in keywords_input.splitlines() if line.strip()]
            crawler = SocialMediaCrawler(profile_url, keywords)
            results = crawler.crawl()
            status.update(label="Complete!", state="complete")

        if results:
            st.success(f"Found **{len(results)}** matching link(s)!")
            
            for i, r in enumerate(results, 1):
                with st.expander(f"Match {i} – {r['keyword']} ({r['location_type']})"):
                    st.write(f"**Source Tweet:** {r['source_url']}")
                    st.write(f"**Matched URL:** {r['matched_url']}")
                    if r['context']:
                        st.caption(f"Context: {r['context']}")

            # CSV Download
            output = StringIO()
            writer = csv.DictWriter(output, fieldnames=results[0].keys())
            writer.writeheader()
            writer.writerows(results)
            st.download_button(
                "Download Results as CSV",
                data=output.getvalue(),
                file_name=f"links_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv"
            )
        else:
            st.warning("No matches found for your keywords.")

st.caption("Social Media Link Scanner • Public profiles only • No login required")
