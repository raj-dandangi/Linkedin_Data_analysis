
import time
import json
import os
import random
import re
import zipfile
from itertools import cycle
import re
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException

# --- Configuration ---
MAX_SCRAPE_CYCLES = 2 # The number of times to loop through the entire account list.
CYCLE_COOLDOWN_SECONDS = 30 # The number of seconds to wait between scrape cycles.
MAX_NEW_COMPANIES = 50000  # Total number of new companies to scrape in this run
COMPANIES_PER_ACCOUNT_RANGE = (500, 1000) # The script will scrape a random number of companies within this range per session.
MAX_SCRAPE_RETRIES = 10 # Number of times to retry scraping a single company on a recoverable error.
MAX_INDUSTRY_SEARCH_ATTEMPTS = 25 # How many different industries to try when seeding the queue.
MAX_SEARCH_PAGES_PER_INDUSTRY = 10 # How many pages of search results to check per industry.

# --- File Paths ---
CREDENTIALS_FILE = "credentials.json"
PROXIES_FILE = "proxies.txt"
DATA_FILE = "scraped_data.json"
BANNED_ACCOUNTS_FILE = "banned_accounts.json"
BAD_PROXIES_FILE = "bad_proxies.txt"

WAIT_TIME = 20  # seconds for waits

PRIORITY_INDUSTRIES = [
    "Software Development",
    "IT Services and IT Consulting",
    "Technology, Information and Internet",
    "Entertainment Providers",
    "Financial Services",
    "Computer Hardware Manufacturing",
    "Research Services","Banking","Translation and Localization","Biotechnology Research"
]

# --- Custom Exception for session-killing errors ---
class SessionInvalidException(Exception):
    """Custom exception for when a session (account/proxy) is no longer valid."""
    pass

def load_blacklist(file_path, is_json=False):
    """Loads a blacklist file."""
    if not os.path.exists(file_path):
        return set()
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            if is_json:
                # For accounts, we use the username as the unique identifier.
                return {item['username'] for item in json.load(f)}
            # For proxies, the whole line is the identifier.
            return {line.strip() for line in f if line.strip()}
    except (IOError, json.JSONDecodeError):
        return set()

def load_existing_data(file_path):
    """Loads existing data and returns the full list and a set of slugs."""
    if not os.path.exists(file_path):
        return [], set()
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data, {item.get('company_slug') for item in data if item.get('company_slug')}
    except (json.JSONDecodeError, IOError):
        return [], set()

def quarantine_asset(asset, file_path, is_json=False):
    """Appends a bad asset to its corresponding quarantine file."""
    print(f"--- QUARANTINING ASSET -> {file_path} ---")
    try:
        if is_json:
            # Read existing, append new, write back
            items = []
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    try:
                        items = json.load(f)
                    except json.JSONDecodeError:
                        pass # File is empty or corrupt, will overwrite
            items.append(asset)
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(items, f, indent=2)
        else:
            # Simple append for text files
            with open(file_path, 'a', encoding='utf-8') as f:
                f.write(asset + '\n')
    except IOError as e:
        print(f"!!! Could not write to quarantine file {file_path}: {e} !!!")

def parse_credentials(file_path):
    """Loads credentials from a JSON file."""
    banned_users = load_blacklist(BANNED_ACCOUNTS_FILE, is_json=True)
    if not os.path.exists(file_path):
        print(f"Credential file not found at {file_path}. Cannot proceed.")
        return []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            credentials = json.load(f)
       
        active_credentials = [c for c in credentials if c['username'] not in banned_users]
        print(f"Loaded {len(active_credentials)} active accounts ({len(banned_users)} banned).")
        return active_credentials
    except (json.JSONDecodeError, IOError) as e:
        print(f"Error reading or parsing credential file at {file_path}: {e}")
        return []

def load_proxies(file_path):
    """Loads proxies from a file (one per line)."""
    bad_proxies = load_blacklist(BAD_PROXIES_FILE)
    if not os.path.exists(file_path):
        print(f"Proxy file not found at {file_path}. Continuing without proxies.")
        return []
    try:
        with open(file_path, 'r') as f:
            proxies = [line.strip() for line in f if line.strip()]
        active_proxies = [p for p in proxies if p not in bad_proxies]
        print(f"Loaded {len(active_proxies)} active proxies ({len(bad_proxies)} banned).")
        return active_proxies
    except IOError as e:
        print(f"Error reading proxy file: {e}")
        return []

def human_like_scroll(driver):
    """
    Simulates more advanced human-like scrolling on a page.
    - Scrolls in chunks with pauses.
    - Varies scroll speed.
    - Occasionally scrolls up.
    - Doesn't always scroll to the absolute bottom.
    """
    try:
        total_height = driver.execute_script("return document.body.scrollHeight")
        if total_height < 1500: # No need for complex scrolling on short pages
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            print("Page is short, scrolled to bottom.")
            return

        # Decide how far down to scroll this time (e.g., 70% to 100% of the page)
        scroll_end_target = total_height * random.uniform(0.7, 1.0)
       
        current_position = 0
        while current_position < scroll_end_target:
            # Determine the next scroll increment
            # Smaller scrolls when near the top, larger in the middle, smaller again at the end
            remaining_distance = scroll_end_target - current_position
            scroll_increment = random.randint(int(remaining_distance * 0.2), int(remaining_distance * 0.5))
            scroll_increment = max(200, min(scroll_increment, 900)) # Clamp scroll size

            driver.execute_script(f"window.scrollBy(0, {scroll_increment});")
           
            # Dynamic sleep time based on position - shorter sleeps for big scrolls at the top
            sleep_time = random.uniform(0.4, 1.0) + (current_position / total_height) # Longer waits as we go down
            time.sleep(sleep_time)
           
            # Small chance to scroll up a bit, like a human re-reading
            if random.random() < 0.15: # 15% chance
                scroll_up_increment = random.randint(100, 400)
                driver.execute_script(f"window.scrollBy(0, -{scroll_up_increment});")
                time.sleep(random.uniform(0.7, 1.6))

            new_position = driver.execute_script("return window.pageYOffset;")
           
            # Break if we are stuck
            if new_position == current_position:
                break
            current_position = new_position
           
            # Chance for a longer "reading" pause
            if random.random() < 0.05: # 5% chance
                print("--- Pausing to 'read' ---")
                time.sleep(random.uniform(2.0, 4.0))

        print("Simulated human-like scrolling.")
    except Exception as e:
        print(f"Could not perform human-like scroll: {e}")

def perform_curiosity_click(driver, wait):
    """With a small chance, clicks a random footer link and navigates back."""
    if random.random() > 0.15: # 85% chance to do nothing
        return
   
    print("--- Performing a 'curiosity' click to appear more human... ---")
    try:
        footer_links_xpath = "//footer//a[contains(@href, 'linkedin.com/legal') or contains(@href, 'linkedin.com/about') or contains(@href, 'linkedin.com/help')]"
        footer_links = driver.find_elements(By.XPATH, footer_links_xpath)
        if footer_links:
            random_link = random.choice(footer_links)
            driver.execute_script("arguments[0].click();", random_link)
            time.sleep(random.uniform(3, 6))
            driver.back()
            wait.until(EC.presence_of_element_located((By.ID, "global-nav-search"))) # Wait for main page to be back
    except Exception as e:
        print(f"Could not perform curiosity click: {e}")

def scrape_company_data(driver, wait, company_slug):
    """
    Scrapes the About and Jobs pages for a given company slug.
    Returns a dictionary of the scraped data.
    """
    scraped_data = {"company_slug": company_slug}
    about_url = f"https://www.linkedin.com/company/{company_slug}/about/"
    jobs_url = f"https://www.linkedin.com/company/{company_slug}/jobs/"

    # --- 1. Scrape the ABOUT page ---
    print(f"\n--- Scraping Company: {company_slug} ---")
    print(f"Navigating to {about_url}...")
    driver.get(about_url)
    check_for_session_errors(driver) # Strategy: Check for blocks immediately
    human_like_scroll(driver) # Add human-like behavior
    # Wait for the top card to load, which contains followers and other primary info.
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".org-top-card")))
    print("Company page loaded.")

    # Scrape Followers
    try:
        # This XPath is more robust as it doesn't rely on dynamic IDs.
        followers_xpath = "//div[contains(@class, 'org-top-card-summary-info-list__info-item') and contains(., 'followers')]"
        followers_element = wait.until(EC.presence_of_element_located((By.XPATH, followers_xpath)))
        scraped_data["followers"] = followers_element.text.strip()
    except TimeoutException:
        print(f"Could not scrape Followers for {company_slug}.")

    # Wait for the main details list to ensure it's loaded before scraping from it.
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "dl")))
    # Scrape Overview
    try:
        overview_xpath = "//h2[normalize-space(.)='Overview']/following-sibling::p"
        description_element = wait.until(EC.presence_of_element_located((By.XPATH, overview_xpath)))
        scraped_data["overview"] = description_element.text.strip()
    except TimeoutException:
        print(f"Could not scrape Overview for {company_slug}.")

    # Scrape other details
    about_details_to_scrape = {"website": "Website", "industry": "Industry", "company_size": "Company size", "headquarters": "Headquarters"}
    for key, label in about_details_to_scrape.items():
        try:
            xpath = f"//dt[normalize-space(.)='{label}']/following-sibling::dd[1]"
            element = wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
            value = element.text.strip().split('\n')[0]
            scraped_data[key] = value
        except TimeoutException:
            print(f"Could not scrape '{label}' for {company_slug}.")

    # --- Add a random delay to mimic human behavior before navigating ---
    sleep_time = random.uniform(4.0, 8.5) # Strategy: Increased and randomized sleep time
    print(f"Pausing for {sleep_time:.2f} seconds to appear more human...")
    time.sleep(sleep_time)

    # --- 2. Scrape the JOBS page ---
    print(f"Navigating directly to {jobs_url}...")
    driver.get(jobs_url)
    check_for_session_errors(driver) # Strategy: Check again on the jobs page
    human_like_scroll(driver) # Add human-like behavior
    try:
        job_headline_xpath = "//h4[contains(@class, 'org-jobs-job-search-form-module__headline')]"
        job_count_element = wait.until(EC.presence_of_element_located((By.XPATH, job_headline_xpath)))
        scraped_data['job_openings_text'] = job_count_element.text.strip()
        print("Jobs page headline loaded.")
    except TimeoutException:
        print(f"Could not scrape job openings count for {company_slug}.")

    # --- 3. Navigate back to About page for discovery ---
    # This is an efficiency improvement to prevent an extra page load in the discover_new_companies function.
    print("Navigating back to About page for discovery...")
    driver.get(about_url)
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "dl")))

    return scraped_data

def check_for_session_errors(driver):
    """
    Checks for CAPTCHA or Access Denied pages, which indicate a burned session.
    Raises SessionInvalidException if a fatal error is found.
    """
    page_title = driver.title.lower()
    page_source = driver.page_source.lower()
    # Strategy: Detect CAPTCHA
    if "security check" in page_title or "prove you're human" in page_source:
        print("!!! CAPTCHA detected. This session is compromised. !!!")
        raise SessionInvalidException("CAPTCHA detected")
    # Strategy: Detect Access Denied
    if "access denied" in page_title or "access to this page has been denied" in page_source:
        print("!!! Access Denied detected. This IP/Account is likely blocked. !!!")
        raise SessionInvalidException("Access Denied")

def is_logged_in(driver):
    """Checks if the user is still logged in by looking for a key element."""
    try:
        # The global navigation search bar is a reliable indicator of being logged in.
        driver.find_element(By.ID, "global-nav-search")
        return True
    except (NoSuchElementException, TimeoutException):
        print("User appears to be logged out (critical navigation element not found).")
        return False

def login_and_setup_driver(credential, proxy=None):
    """Initializes a new driver, logs in, and returns driver and wait objects."""
    print("\n" + "="*50)
    print(f"Attempting to log in with account: {credential['username']}")
    if proxy:
        # Don't log username/password of proxy
        print(f"Using proxy: {proxy.split('@')[-1]}")
    print("="*50)

    # WebDriver setup
    chrome_options = Options()

    if proxy:
        proxy_host, proxy_port, proxy_user, proxy_pass = proxy.split(':')
        manifest_json = """
        {
            "version": "1.0.0", "manifest_version": 2, "name": "Chrome Proxy",
            "permissions": ["proxy", "tabs", "unlimitedStorage", "storage", "<all_urls>", "webRequest", "webRequestBlocking"],
            "background": {"scripts": ["background.js"]}
        }
        """
        background_js = f"""
        var config = {{
            mode: "fixed_servers",
            rules: {{singleProxy: {{scheme: "http", host: "{proxy_host}", port: parseInt({proxy_port})}}, bypassList: ["localhost"]}}
        }};
        chrome.proxy.settings.set({{value: config, scope: "regular"}}, function() {{}});
        function callbackFn(details) {{return {{authCredentials: {{username: "{proxy_user}", password: "{proxy_pass}"}}}}}}
        chrome.webRequest.onAuthRequired.addListener(callbackFn, {{urls: ["<all_urls>"]}}, ['blocking']);
        """
        plugin_file = 'proxy_auth_plugin.zip'
        with zipfile.ZipFile(plugin_file, 'w') as zp:
            zp.writestr("manifest.json", manifest_json)
            zp.writestr("background.js", background_js)
        chrome_options.add_extension(plugin_file)

    chrome_options.add_argument("--log-level=3")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080") # Strategy: Consistent browser fingerprint
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36")

    driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=chrome_options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    wait = WebDriverWait(driver, WAIT_TIME)

    # Dynamic cookie file based on username
    safe_username = ''.join(c for c in credential['username'] if c.isalnum())
    cookie_file = f"linkedin_cookies_{safe_username}.json"

    logged_in = False
    # Try cookie login
    if os.path.exists(cookie_file):
        print(f"Found session cookies at '{cookie_file}'. Attempting to log in...")
        driver.get("https://www.linkedin.com")
        with open(cookie_file, 'r') as f:
            cookies = json.load(f)
        for cookie in cookies:
            driver.add_cookie(cookie)
        driver.get("https://www.linkedin.com/feed/")
        try:
            wait.until(EC.presence_of_element_located((By.ID, "global-nav-search")))
            print("Successfully logged in using cookies.")
            logged_in = True
        except TimeoutException:
            print("Cookie-based login failed. Cookies might be stale.")
            os.remove(cookie_file)

    if not logged_in:
        print("Performing username/password login...")
        driver.get("https://www.linkedin.com/login")
        username_field = wait.until(EC.presence_of_element_located((By.ID, "username")))
        username_field.send_keys(credential['username'])
        password_field = driver.find_element(By.ID, "password")
        password_field.send_keys(credential['password'])
        password_field.send_keys(Keys.RETURN)
        try:
            wait.until(EC.presence_of_element_located((By.ID, "global-nav-search")))
            print("Login successful.")
            logged_in = True
            print(f"Saving session cookies to '{cookie_file}' for future use...")
            with open(cookie_file, "w") as f:
                json.dump(driver.get_cookies(), f)
        except TimeoutException:
            print("\n" + "!"*15 + " LOGIN FAILED " + "!"*15)
            print(f"-> Failed Account: {credential['username']}")
            if proxy:
                print(f"-> Proxy Used: {proxy.split('@')[-1]}")
            print("-> Reason: Could not log in. The account may be locked, require a CAPTCHA, or have incorrect credentials.")
            print("!"*44)
            # This is a definitive account failure. Quarantine it.
            quarantine_asset(credential, BANNED_ACCOUNTS_FILE, is_json=True)

    if not logged_in:
        driver.quit()
        return None, None

    return driver, wait

def find_company_via_search(driver, wait, scraped_slugs, max_pages_to_check=10):
    """
    Uses LinkedIn search to find a new company, clicks it, and returns its slug.
    Returns the slug of the new company if found, otherwise returns None.
    """
    print("\n--- Attempting discovery via LinkedIn search... ---")
    try:
        search_input_xpath = "//input[contains(@class, 'search-global-typeahead__input')]"
        search_input = wait.until(EC.presence_of_element_located((By.XPATH, search_input_xpath)))
        search_input.clear()

        search_term = random.choice(PRIORITY_INDUSTRIES)
        print(f"Searching for companies in industry: '{search_term}'")

        search_input.send_keys(search_term)
        search_input.send_keys(Keys.RETURN)

        # UPDATED STRATEGY: The previous wait for 'search-reusables__filters-bar' was brittle
        # and caused timeouts when LinkedIn changed its UI. The new strategy is to wait
        # directly for the 'Companies' filter button to be clickable.
