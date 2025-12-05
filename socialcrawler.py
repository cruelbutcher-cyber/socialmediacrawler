#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Enhanced Social Media Crawler with Streamlit GUI
Searches for specified keywords in URLs, content, and redirects on a social media profile.
Features:
- Web scraping with BeautifulSoup
- Selenium for dynamic loading
- Configurable keywords
- CSV export of results
"""

import streamlit as st
import requests
from bs4 import BeautifulSoup, FeatureNotFound
from urllib.parse import urljoin, urlparse, parse_qs, unquote, urlunparse
from collections import deque
import csv
import datetime
import re
import time
from io import StringIO
import hashlib
import html
import tldextract
from urllib3.util import Retry
from requests.adapters import HTTPAdapter
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

class EnhancedWebCrawler:
    def __init__(self, start_url, keywords=None, status_callback=None):
        self.session = self._create_session()
        self.start_url = start_url
        self.keywords = keywords if keywords else ["gowithguide", "go with guide", "go-with-guide"]
        self.main_domain = urlparse(start_url).netloc
        self.max_pages = 5000  # Equivalent to original "Complete" mode
        self.visited = set()
        self.results = []
        self.queue = deque([start_url])
        self.user_stopped = False
        self.pages_crawled = 0
        self.redirect_cache = {}
        self.internal_links = set()
        self.known_shorteners = [
            'bit.ly', 'tinyurl.com', 'goo.gl', 't.co', 'ow.ly', 'is.gd',
            'buff.ly', 'adf.ly', 'bit.do', 'mcaf.ee', 'su.pr', 'tiny.cc',
            'tidd.ly', 'redirectingat.com', 'go.redirectingat.com', 'go.skimresources.com'
        ]
        self.awin_domains = ['awin1.com', 'zenaps.com']
        self.potential_affiliate_domains = [
            'track.', 'go.', 'click.', 'buy.', 'shop.', 'link.', 'visit.',
            'affiliate.', 'partners.', 'tracking.', 'redirect.', 'ref.'
        ]
        self.potential_affiliate_paths = [
            '/visit', '/go', '/goto', '/redirect', '/click', '/buy', '/shop',
            '/link', '/affiliate', '/partner', '/tracking', '/ref', '/out'
        ]
        self.potential_affiliate_params = [
            'site', 'url', 'link', 'goto', 'target', 'redirect', 'redirect_to',
            'dest', 'destination', 'u', 'to', 'out', 'away', 'href'
        ]
        self.crawled_pages_content = {}
        self.url_fragments_checked = set()
        self.status_callback = status_callback
        self.driver = None
        self._detect_social_media()
    
    def _detect_social_media(self):
        parsed = urlparse(self.start_url)
        path_parts = parsed.path.strip('/').split('/')
        if 'x.com' in self.main_domain or 'twitter.com' in self.main_domain:
            if path_parts:
                self.username = path_parts[0]
            if self.username:
                self.start_url = f'https://{self.main_domain}/{self.username}/with_replies'
                self.queue = deque([self.start_url])
    
    def _create_session(self):
        session = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "HEAD"]
        )
        adapter = HTTPAdapter(max_retries=retries)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Cache-Control': 'max-age=0'
        })
        return session
    
    def get_soup(self, html_content):
        try:
            return BeautifulSoup(html_content, 'lxml')
        except FeatureNotFound:
            if self.status_callback:
                self.status_callback("Warning: 'lxml' parser not found. Using 'html.parser' instead.")
            return BeautifulSoup(html_content, 'html.parser')
    
    def is_same_domain(self, url):
        main_domain_parts = tldextract.extract(self.start_url)
        url_domain_parts = tldextract.extract(url)
        return (main_domain_parts.domain == url_domain_parts.domain and
                main_domain_parts.suffix == url_domain_parts.suffix)
    
    def is_subdomain_of(self, url_netloc):
        main_domain = self.main_domain.replace("www.", "").lower()
        url_netloc = url_netloc.replace("www.", "").lower()
        return url_netloc.endswith("." + main_domain) or url_netloc == main_domain
    
    def is_relevant_path(self, url):
        parsed_url = urlparse(url)
        path = parsed_url.path.lower()
        if re.search(r'\.(jpg|jpeg|png|gif|svg|pdf|zip|rar|css|js|xml|json)$', path):
            return False
        if re.search(r'/(login|logout|register|signin|signout|cart|checkout|privacy|terms)/?$', path):
            return False
        if re.search(r'/(post|article|blog|news|story|travel|guide|destination|affiliate|status|video|reel|short|channel|playlist)/', path):
            return True
        if len(parse_qs(parsed_url.query)) > 3:
            return False
        return True
    
    def normalize_url(self, url):
        parsed = urlparse(url)
        normalized = urlunparse((parsed.scheme, parsed.netloc, parsed.path,
                                parsed.params, parsed.query, ''))
        if normalized.endswith('/'):
            normalized = normalized[:-1]
        return normalized
    
    def looks_like_affiliate_url(self, url):
        url_lower = url.lower()
        parsed_url = urlparse(url_lower)
        netloc = parsed_url.netloc
        path = parsed_url.path
        
        if any(shortener in netloc for shortener in self.known_shorteners):
            return True
        
        if any(tracker in netloc for tracker in self.potential_affiliate_domains):
            return True
        
        if any(domain in netloc for domain in self.awin_domains):
            query_params = parse_qs(parsed_url.query)
            if 'v' in query_params and query_params['v'][0] == '87121':
                return True
            if 'awinmid' in query_params and query_params['awinmid'][0] == '87121':
                return True
        
        if any(aff_path in path for aff_path in self.potential_affiliate_paths):
            return True
        
        query_params = parse_qs(parsed_url.query)
        affiliate_params = ['aff', 'affid', 'affiliateid', 'ref', 'refid', 'referral',
                           'referralid', 'partner', 'partnerId', 'utm_source']
        for param in affiliate_params:
            if param in query_params:
                return True
        
        for param in self.potential_affiliate_params:
            if param in query_params:
                param_value = query_params[param][0].lower()
                if any(keyword in param_value for keyword in self.keywords):
                    return True
        
        tracking_params = ['utm_', 'ref', 'aff', 'source', 'campaign', 'medium']
        tracking_count = sum(1 for param in query_params if any(t in param for t in tracking_params))
        if tracking_count >= 2:
            return True
        
        if 'awc' in query_params:
            awc_value = query_params['awc'][0]
            if '87121' in awc_value:
                return True
        
        return False
    
    def extract_redirection_url(self, html_content, url):
        soup = self.get_soup(html_content)
        redirect_urls = []
        meta_refresh = soup.find('meta', attrs={'http-equiv': re.compile('^refresh$', re.I)})
        if meta_refresh and meta_refresh.get('content'):
            match = re.search(r'url=(.+)', meta_refresh['content'], re.I)
            if match:
                redirect_url = match.group(1).strip()
                redirect_urls.append(urljoin(url, redirect_url))
        script_patterns = [
            r'window\.location(?:\.href)?\s*=\s*[\'"](.+?)[\'"]',
            r'window\.location\.replace\([\'"](.+?)[\'"]\)',
            r'window\.open\([\'"](.+?)[\'"]\)',
            r'location\.href\s*=\s*[\'"](.+?)[\'"]',
            r'location\.replace\([\'"](.+?)[\'"]\)',
            r'setTimeout\([\'"]window\.location\.href=[\'"](.+?)[\'"][\'"]',
            r'url:\s*[\'"](.+?)[\'"]',
            r'href=[\'"](.+?)[\'"]'
        ]
        scripts = soup.find_all('script')
        for script in scripts:
            if script.string:
                for pattern in script_patterns:
                    matches = re.findall(pattern, script.string)
                    for match in matches:
                        if len(match) > 10:
                            redirect_urls.append(urljoin(url, match))
        parsed_url = urlparse(url)
        query_params = parse_qs(parsed_url.query)
        redirect_params = ['redirect_to', 'redirect', 'url', 'link', 'goto', 'target', 'ued']
        for param in redirect_params:
            if param in query_params:
                decoded_url = unquote(query_params[param][0])
                redirect_urls.append(urljoin(url, decoded_url))
        return redirect_urls
    
    def check_url_for_keywords(self, url, source_url):
        if not url or not isinstance(url, str):
            return
        url_hash = hashlib.md5(url.encode()).hexdigest()
        if url_hash in self.url_fragments_checked:
            return
        self.url_fragments_checked.add(url_hash)
        matched_kws = self.get_matched_keywords(url)
        if matched_kws:
            self.add_result(
                source_url=source_url,
                matched_url=url,
                element='url',
                attribute='href',
                content=url,
                keywords=matched_kws,
                location_type='direct_url'
            )
        if self.looks_like_affiliate_url(url):
            final_url = self.resolve_redirects(url)
            if final_url != url:
                matched_kws_final = self.get_matched_keywords(final_url)
                if matched_kws_final:
                    self.add_result(
                        source_url=source_url,
                        matched_url=final_url,
                        element='url',
                        attribute='href',
                        content=f"Redirected from: {url} to: {final_url}",
                        keywords=matched_kws_final,
                        location_type='redirected_url'
                    )
    
    def get_matched_keywords(self, text):
        if not text or not isinstance(text, str):
            return []
        matched = []
        text_lower = text.lower()
        for keyword in self.keywords:
            if keyword.lower() in text_lower:
                matched.append(keyword)
        return matched
    
    def add_result(self, source_url, matched_url, element, attribute, content, keywords, location_type):
        result = {
            'source_url': source_url,
            'matched_url': matched_url,
            'keyword': ', '.join(keywords),
            'location_type': location_type,
            'element': element,
            'attribute': attribute,
            'content': content,
            'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        self.results.append(result)
        if self.status_callback:
            self.status_callback(f"Found match: {matched_url} (Keyword: {result['keyword']})")
    
    def resolve_redirects(self, url):
        if url in self.redirect_cache:
            return self.redirect_cache[url]
        try:
            response = self.session.head(url, allow_redirects=True, timeout=5)
            final_url = response.url
            self.redirect_cache[url] = final_url
        except requests.RequestException:
            final_url = url
            self.redirect_cache[url] = url
        return final_url
    
    def process_url(self, url):
        if url in self.visited or self.pages_crawled >= self.max_pages or not url or self.user_stopped:
            return []
        self.visited.add(url)
        self.pages_crawled += 1
        if self.status_callback:
            self.status_callback(f"Processing page {self.pages_crawled}: {url}")
        try:
            # Use Selenium for dynamic loading
            options = Options()
            options.add_argument("--headless")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
            options.binary_location = "/usr/bin/chromium-browser"  # For cloud compatibility
            self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
            self.driver.get(url)
            time.sleep(2)  # Initial load
            last_height = self.driver.execute_script("return document.body.scrollHeight")
            while not self.user_stopped:
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2)
                new_height = self.driver.execute_script("return document.body.scrollHeight")
                if new_height == last_height:
                    break
                last_height = new_height
            html_content = self.driver.page_source
            self.driver.quit()
            self.driver = None
            
            soup = self.get_soup(html_content)
            matched_kws = self.get_matched_keywords(html_content)
            if matched_kws:
                self.add_result(
                    source_url=url,
                    matched_url=url,
                    element='page_content',
                    attribute='text',
                    content=html_content[:200],
                    keywords=matched_kws,
                    location_type='content'
                )
            redirect_urls = self.extract_redirection_url(html_content, url)
            for redirect_url in redirect_urls:
                self.check_url_for_keywords(redirect_url, url)
            links = []
            for a_tag in soup.find_all('a', href=True):
                href = a_tag.get('href')
                if not href:
                    continue
                absolute_url = urljoin(url, href)
                absolute_url = self.normalize_url(absolute_url)
                if (self.is_same_domain(absolute_url) or self.is_subdomain_of(urlparse(absolute_url).netloc)) and self.is_relevant_path(absolute_url):
                    links.append(absolute_url)
                    self.internal_links.add(absolute_url)
                self.check_url_for_keywords(absolute_url, url)
            return links
        except Exception as e:
            if self.status_callback:
                self.status_callback(f"Error processing {url}: {str(e)}")
            return []
    
    def start_crawling(self):
        self.reset_state()
        if self.status_callback:
            self.status_callback(f"Starting crawl of {self.start_url}")
        while self.queue and not self.user_stopped and self.pages_crawled < self.max_pages:
            url = self.queue.popleft()
            new_urls = self.process_url(url)
            for new_url in new_urls:
                if (new_url not in self.visited and new_url not in self.queue and
                        self.pages_crawled < self.max_pages):
                    self.queue.append(new_url)
            if self.results:
                if self.status_callback:
                    self.status_callback(f"Found {len(self.results)} matches")
        if self.status_callback:
            self.status_callback("Crawling completed")
        return self.results
    
    def reset_state(self):
        self.visited = set()
        self.queue = deque([self.start_url])
        self.results = []
        self.pages_crawled = 0
        self.redirect_cache = {}
        self.internal_links = set()
        self.crawled_pages_content = {}
        self.url_fragments_checked = set()

def generate_csv(results):
    csv_file = StringIO()
    writer = csv.DictWriter(csv_file, fieldnames=[
        'source_url', 'matched_url', 'keyword',
        'location_type', 'element', 'attribute',
        'content_sample', 'timestamp'
    ])
    writer.writeheader()
    for result in results:
        writer.writerow({
            'source_url': result['source_url'],
            'matched_url': result['matched_url'],
            'keyword': result['keyword'],
            'location_type': result['location_type'],
            'element': result['element'],
            'attribute': result['attribute'],
            'content_sample': result['content'][:300] if result['content'] else '',
            'timestamp': result['timestamp']
        })
    return csv_file.getvalue()

# Streamlit GUI
st.header("Crawler Settings")
profile_url = st.text_input("Social Media Profile URL", value="https://www.youtube.com/@example")
keywords_input = st.text_area("Keywords (comma-separated)", value="gowithguide, go with guide, go-with-guide")

if st.button("Start Crawling"):
    keywords = [k.strip() for k in keywords_input.split(',') if k.strip()]
    if not profile_url or not keywords:
        st.error("Please provide a URL and keywords.")
    else:
        crawler = EnhancedWebCrawler(profile_url, keywords, status_callback=st.write)
        results = crawler.start_crawling()
        if results:
            st.success(f"Found {len(results)} matches.")
            csv_data = generate_csv(results)
            st.download_button("Download CSV", csv_data, file_name="crawl_results.csv", mime="text/csv")
        else:
            st.info("No matches found.")
