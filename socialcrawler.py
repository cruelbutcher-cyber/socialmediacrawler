#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Streamlit Enhanced Social Media Crawler
Searches all outgoing links in a public X/Twitter profile for specific keywords.
"""

import streamlit as st
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs, unquote
import re
import time
import hashlib
import csv
from io import StringIO
from datetime import datetime
import tldextract
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

# --------------------------- Configuration ---------------------------
st.set_page_config(
    page_title="Social Media Link Scanner",
    page_icon="magnifyingglass",
    layout="wide"
)

st.title("Enhanced Social Media Link Scanner")
st.markdown("""
Search **all outgoing links** from a public X/Twitter profile (or any public social profile)  
for specific keywords — including inside shortened/affiliate/redirected URLs.
""")

# --------------------------- Core Logic ---------------------------
class SocialMediaCrawler:
    def __init__(self, profile_url, keywords):
        self.profile_url = profile_url.rstrip("/")
        self.keywords = [k.strip().lower() for k in keywords if k.strip()]
        self.results = []
        self.visited = set()
        self.redirect_cache = {}
        self.url_checked = set()

        self.known_shorteners = {
            'bit.ly', 'tinyurl.com', 't.co', 'goo.gl', 'ow.ly', 'is.gd',
            'buff.ly', 'adf.ly', 'bit.do', 'mcaf.ee', 'tiny.cc'
        }

    def is_likely_affiliate(self, url):
        url_l = url.lower()
        parsed = urlparse(url_l)
        if any(dom in parsed.netloc for dom in self.known_shorteners):
            return True
        if any(prefix in parsed.netloc for prefix in ['track.', 'go.', 'click.', 'ref.', 'link.']):
            return True
        if 'awin1.com' in parsed.netloc or 'zenaps.com' in parsed.netloc:
            return True
        return False

    def resolve_redirect(self, url):
        if url in self.redirect_cache:
            return self.redirect_cache[url]
        try:
            resp = requests.head(url, allow_redirects=True, timeout=8)
            self.redirect_cache[url] = resp.url
            return resp.url
        except:
            self.redirect_cache[url] = url
            return url

    def match_keywords(self, text):
        if not text:
            return []
        text_l = text.lower()
        return [kw for kw in self.keywords if kw in text_l]

    def add_result(self, source_url, matched_url, location_type, content=""):
        self.results.append({
            "source_url": source_url,
            "matched_url": matched_url,
            "keyword": ", ".join(self.match_keywords(matched_url)),
            "location_type": location_type,
            "content_preview": content[:200],
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

    def extract_links_from_page(self, html, base_url):
        soup = BeautifulSoup(html, "html.parser")
        links = set()

        for a in soup.find_all("a", href=True):
            href = a["href"]
            full_url = urljoin(base_url, href.split("?")[0])  # clean fragments
            full_url = full_url.split("#")[0]

            if full_url in self.url_checked:
                continue
            self.url_checked.add(full_url)

            # Direct keyword match in URL
            matched = self.match_keywords(full_url)
            if matched:
                self.add_result(base_url, full_url, "direct_url", str(a.text)[:100])

            # Affiliate/redirect suspicion → resolve
            if self.is_likely_affiliate(full_url):
                final = self.resolve_redirect(full_url)
                if final != full_url:
                    final_matched = self.match_keywords(final)
                    if final_matched:
                        self.add_result(
                            base_url, final, "redirected_url",
                            f"Original: {full_url} → Final: {final}"
                        )

            # Always collect internal post links (for crawling)
            parsed = urlparse(full_url)
            if parsed.netloc.endswith("x.com") or parsed.netloc.endswith("twitter.com"):
                path_parts = parsed.path.strip("/").split("/")
                if len(path_parts) >= 3 and path_parts[1] == "status":
                    links.add(full_url)

        return links

    def crawl_profile(self, progress_bar=None):
        with st.spinner("Launching browser and loading profile..."):
            options = Options()
            options.add_argument("--headless")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

            driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
            driver.get(self.profile_url + "?s=20")  # helps trigger full load

        st.info("Scrolling through timeline to load all posts... (this may take 30–90 seconds)")

        last_height = driver.execute_script("return document.body.scrollHeight")
        scrolls = 0
        while True:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2.5)
            new_height = driver.execute_script("return document.body.scrollHeight")
            scrolls += 1
            if progress_bar:
                progress_bar.progress(min(scrolls / 30, 1.0))

            if new_height == last_height or scrolls > 30:  # max ~2–3 min scroll
                break
            last_height = new_height

        html = driver.page_source
        driver.quit()

        st.success(f"Loaded profile page • Found {len(re.findall(r'/status/\d+', html))} posts")

        with st.spinner("Extracting and analyzing all outgoing links..."):
            post_urls = re.findall(r'https?://(?:x\.com|twitter\.com)/[^"\']+/status/\d+', html)
            all_links = self.extract_links_from_page(html, self.profile_url)

            for post_url in post_urls:
                if post_url not in self.visited:
                    self.visited.add(post_url)
                    try:
                        resp = requests.get(post_url, timeout=15)
                        all_links.update(self.extract_links_from_page(resp.text, post_url))
                    except:
                        continue

        return self.results

# --------------------------- Streamlit UI ---------------------------
with st.sidebar:
    st.header("Settings")
    profile_url = st.text_input(
        "Public Profile URL",
        value="https://x.com/example",
        help="e.g., https://x.com/elonmusk or https://twitter.com/verge"
    )

    keyword_input = st.text_area(
        "Keywords to find (one per line)",
        value="gowithguide\ngo with guide\ngo-with-guide",
        height=150,
        help="Case-insensitive. Will match in final URLs after redirects too."
    )

    if st.button("Start Scanning", type="primary", use_bias=True"):
        if not profile_url.strip():
            st.error("Please enter a profile URL")
        elif not keyword_input.strip():
            st.error("Please enter at least one keyword")
        else:
            keywords = [line.strip() for line in keyword_input.splitlines() if line.strip()]
            crawler = SocialMediaCrawler(profile_url, keywords)

            progress = st.progress(0)
            status_text = st.empty()

            status_text.info("Starting crawl...")
            results = crawler.crawl_profile(progress)

            st.session_state.results = results
            progress.empty()
            status_text.empty()

if "results" in st.session_state:
    results = st.session_state.results

    if results:
        st.success(f"Scan complete! Found **{len(results)}** matching link(s)")
        
        # Display results
        for i, r in enumerate(results, 1):
            with st.expander(f"Match {i} • {r['keyword']} • {r['location_type']}"):
                st.write(f"**Source:** {r['source_url']}")
                st.write(f"**Matched URL:** {r['matched_url']}")
                st.write(f"**Keyword(s):** {r['keyword']}")
                if r['content_preview']:
                    st.caption(f"Context: {r['content_preview']}")

        # CSV Export
        csv_buffer = StringIO()
        writer = csv.DictWriter(csv_buffer, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)

        st.download_button(
            label="Download Results as CSV",
            data=csv_buffer.getvalue(),
            file_name=f"social_scan_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv"
        )
    else:
        st.warning("No matches found for the given keywords.")
