# an average of 15min per 10 account 1 accout takes 1.5min 
import time
import json
import os
import random
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
MAX_SCRAPE_CYCLES = 5 # The number of times to loop through the entire account list.
CYCLE_COOLDOWN_MINUTES = 5 # The number of minutes to wait between scrape cycles.
MAX_NEW_COMPANIES = 500  # Total number of new companies to scrape in this run
COMPANIES_PER_ACCOUNT_RANGE = (50, 50) # The script will scrape a random number of companies within this range per session.
MAX_SCRAPE_RETRIES = 3 # Number of times to retry scraping a single company on a recoverable error.
MAX_INDUSTRY_SEARCH_ATTEMPTS = 50 # How many different industries to try when seeding the queue.
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

def save_data(data, file_path):
    """Saves the provided data to a JSON file."""
    if not data:
        return
    print(f"\nSaving {len(data)} total companies to '{file_path}'...")
    try:
        with open(file_path, "w", encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"Data successfully saved to '{file_path}'")
    except IOError as e:
        print(f"!!! CRITICAL: Could not save data to file: {e} !!!")

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
    """Simulates human-like scrolling on a page to mimic user behavior."""
    try:
        total_height = driver.execute_script("return document.body.scrollHeight")
        current_position = driver.execute_script("return window.pageYOffset;")
        
        while current_position < total_height:
            # Scroll down by a random fraction of the viewport height
            scroll_increment = random.randint(300, 600)
            driver.execute_script(f"window.scrollBy(0, {scroll_increment});")
            time.sleep(random.uniform(0.4, 1.2))
            
            # Small chance to scroll up a bit, like a human re-reading
            if random.random() < 0.1: # 10% chance
                scroll_up_increment = random.randint(100, 300)
                driver.execute_script(f"window.scrollBy(0, -{scroll_up_increment});")
                time.sleep(random.uniform(0.6, 1.5))

            new_position = driver.execute_script("return window.pageYOffset;")
            total_height = driver.execute_script("return document.body.scrollHeight") # Recalculate in case of lazy loading
            
            # Break if we are stuck at the bottom or not moving
            if new_position == current_position:
                break
            current_position = new_position
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
    sleep_time = random.uniform(10.0, 15.0) # Strategy: Increased and randomized sleep time
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

        # Click on the "Companies" filter
        companies_button_xpath = "//button[text()='Companies']"
        companies_button = wait.until(EC.element_to_be_clickable((By.XPATH, companies_button_xpath)))
        companies_button.click()
        print("Filtered search results for 'Companies'.")

        # Loop through search result pages
        for page_num in range(max_pages_to_check):
            print(f"Parsing search results page {page_num + 1}/{max_pages_to_check}...")
            wait.until(EC.presence_of_element_located((By.CLASS_NAME, "search-results-container")))
            human_like_scroll(driver)

            # Find all individual company result containers on the page.
            # This locator targets the main div for each search result via a stable data attribute,
            # which is more resilient to UI changes than obfuscated class names.
            company_containers = driver.find_elements(By.XPATH, "//div[@data-chameleon-result-urn]")
            print(f"Found {len(company_containers)} potential company containers on page.")

            new_companies_on_page = []
            for container in company_containers:
                try:
                    # Strategy: Skip LinkedIn's auto-generated "Skill Pages" as they are not real companies.
                    try:
                        skill_page_indicator = container.find_element(By.XPATH, ".//span[contains(., 'Page by LinkedIn Skill Pages')]")
                        if skill_page_indicator:
                            print("  - Skipping a 'LinkedIn Skill Page'.")
                            continue
                    except NoSuchElementException:
                        # This is good, it's not a skill page.
                        pass

                    # Find the main title link which contains both the name and the href.
                    # The 't-16' class is a typography class for the title, making it a good target.
                    title_link_element = container.find_element(By.XPATH, ".//span[contains(@class, 't-16')]/a")

                    href = title_link_element.get_attribute('href')
                    if not href: continue

                    slug = _extract_slug_from_href(href) # Use the robust regex helper

                    if slug and slug not in scraped_slugs:
                        company_name = title_link_element.text.strip()
                        if not company_name: company_name = "Unknown" # Fallback in case the text is empty

                        new_companies_on_page.append({
                            "name": company_name, "slug": slug, "element": title_link_element
                        })
                except (NoSuchElementException, IndexError):
                    continue
            
            if new_companies_on_page:
                print(f"\n>>> Found {len(new_companies_on_page)} new seed companies on this page:")
                for company in new_companies_on_page:
                    print(f"  - {company['name']} (slug: {company['slug']})")
                selected_company = new_companies_on_page[0]
                print(f"\nSelecting '{selected_company['name']}' to start the scraping queue.")
                # The main loop will handle navigation. We just return the slug.
                return selected_company['slug']

            try:
                next_button = driver.find_element(By.XPATH, "//button[@aria-label='Next']")
                if "artdeco-button--disabled" in next_button.get_attribute("class"):
                    print("No more search result pages.")
                    break
                driver.execute_script("arguments[0].click();", next_button)
                time.sleep(random.uniform(2, 4))
            except NoSuchElementException:
                print("No 'Next' button found. Ending search.")
                break
        
        print("Search discovery method did not find any new companies within the page limit.")
        return None
    except Exception as e:
        print(f"An error occurred during search-based discovery: {e}")
        return None

def _extract_slug_from_href(href):
    """Extracts a company or showcase slug from a LinkedIn URL using regex."""
    if not href:
        return None
    # Handles URLs like /company/slug/ or /showcase/slug?some_param=...
    match = re.search(r'/(?:company|showcase)/([^/?]+)', href)
    return match.group(1) if match else None

def _process_discovery_modal(driver, wait, scraped_slugs, discovery_queue):
    """
    Helper function to process companies from a discovery modal.
    Returns True if new companies were added, False otherwise.
    """
    modal_xpath = "//div[contains(@class, 'artdeco-modal__content')]"
    modal_content = wait.until(EC.presence_of_element_located((By.XPATH, modal_xpath)))
    print("Modal opened. Scrolling to load all companies...")

    # Scroll inside the modal to load all companies
    last_height = 0
    for _ in range(10): # Limit scrolls to prevent infinite loops
        driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight", modal_content)
        time.sleep(2)
        new_height = driver.execute_script("return arguments[0].scrollHeight", modal_content)
        if new_height == last_height:
            break
        last_height = new_height
    print("Finished scrolling modal.")

    priority_slugs = set()
    fallback_slugs = set()

    company_cards = modal_content.find_elements(By.XPATH, ".//div[contains(@class, 'org-view-entity-card__container')]")
    print(f"Found {len(company_cards)} companies in the modal for filtering.")

    for card in company_cards:
        try:
            # Strategy: Skip LinkedIn's auto-generated "Skill Pages" as they are not real companies.
            try:
                skill_page_indicator = card.find_element(By.XPATH, ".//span[contains(., 'Page by LinkedIn Skill Pages')]")
                if skill_page_indicator:
                    print("  - Skipping a 'LinkedIn Skill Page' in modal.")
                    continue
            except NoSuchElementException:
                pass

            link_element = card.find_element(By.XPATH, ".//a[contains(@href, '/company/') or contains(@href, '/showcase/')]")
            slug = _extract_slug_from_href(link_element.get_attribute('href'))

            if not slug or slug in scraped_slugs or slug in discovery_queue:
                continue

            industry = card.find_element(By.XPATH, ".//div[contains(@class, 'artdeco-entity-lockup__subtitle')]//span").text.strip()
            
            if industry in PRIORITY_INDUSTRIES:
                priority_slugs.add(slug)
            else:
                fallback_slugs.add(slug)
        except NoSuchElementException:
            continue # Skip if card is not a valid company entry

    new_slugs_to_add = list(priority_slugs) or list(fallback_slugs)

    print("Closing modal...")
    driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.ESCAPE)
    time.sleep(1)

    if new_slugs_to_add:
        discovery_queue.extend(new_slugs_to_add)
        print(f"Added {len(new_slugs_to_add)} new unique slugs to the discovery queue: {new_slugs_to_add}")
        return True
    else:
        print("No new unique companies found in this modal.")
        return False

def discover_new_companies(driver, wait, scraped_slugs, discovery_queue, current_slug):
    """
    Navigates to a company's about page and discovers new companies to add to the queue.
    Prioritizes the 'Show all' modal, then falls back to other methods.
    """
    print(f"\n--- Discovering new companies from '{current_slug}' ---")
    # Navigation is now handled at the end of scrape_company_data to be more efficient.
    human_like_scroll(driver) # Add human-like behavior

    try:
        # Wait for the main content to ensure the page is ready
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "dl")))

        # --- PRIMARY DISCOVERY: "Show all" button for "Recommended pages" ---
        try:
            show_all_button_xpath = "//button[.//span[normalize-space()='Show all'] and contains(@aria-label, 'recommended pages')]"
            show_all_button = wait.until(EC.element_to_be_clickable((By.XPATH, show_all_button_xpath)))
            print("Found 'Show all' button for 'recommended pages'. Clicking to open modal...")
            driver.execute_script("arguments[0].click();", show_all_button)
            found_new = _process_discovery_modal(driver, wait, scraped_slugs, discovery_queue)
            if found_new:
                return # Exit discovery if this method was fruitful
        except (NoSuchElementException, TimeoutException):
            print("Primary discovery method ('Show all' for recommended pages) not found. Trying next method.")

        # --- SECONDARY DISCOVERY: "Pages people also viewed" (Scrape visible links AND check for modal) ---
        new_slugs_for_queue = set()

        # Step A: Scrape visible links in the section first
        try:
            visible_links_xpath = "//h3[normalize-space()='Pages people also viewed']/ancestor::div[contains(@class, 'cards-group__card-spacing')]//a[.//div[contains(@class, 'artdeco-entity-lockup__title')]]"
            visible_links = driver.find_elements(By.XPATH, visible_links_xpath)
            if visible_links:
                print(f"Found {len(visible_links)} visible links in 'Pages people also viewed'.")
                for link_element in visible_links:
                    href = link_element.get_attribute('href')
                    slug = _extract_slug_from_href(href)
                    if slug and slug not in scraped_slugs and slug not in discovery_queue:
                        new_slugs_for_queue.add(slug)
        except NoSuchElementException:
            print("No visible links found in 'Pages people also viewed' section.")

        # Step B: Click the modal button if it exists
        try:
            show_all_button_xpath = "//h3[normalize-space()='Pages people also viewed']/ancestor::div[contains(@class, 'cards-group__card-spacing')]//button[contains(@aria-label, 'Show all similar pages')]"
            show_all_button = wait.until(EC.element_to_be_clickable((By.XPATH, show_all_button_xpath)))
            print("Found 'Show all' button for 'Pages people also viewed'. Clicking to open modal...")
            driver.execute_script("arguments[0].click();", show_all_button)
            found_new = _process_discovery_modal(driver, wait, scraped_slugs, discovery_queue)
            if found_new:
                return # Exit discovery if this method was fruitful
        except (NoSuchElementException, TimeoutException):
            print("Secondary discovery method ('Show all' for 'Pages people also viewed') not found. Trying fallback.")

        if new_slugs_for_queue:
            discovery_queue.extend(list(new_slugs_for_queue))
            print(f"Added {len(new_slugs_for_queue)} new unique slugs from visible links: {list(new_slugs_for_queue)}")
            return # Exit if we found slugs from the visible part of this section

        # --- FALLBACK DISCOVERY METHODS ---        
        # Strategy: Find the container first, then check its contents. This is more robust
        # and allows us to filter out unwanted results like "Skill Pages".
        primary_container_xpath = "//h3[normalize-space()='People also follow' or normalize-space()='Pages people also viewed' or normalize-space()='Affiliated pages']/ancestor::div[contains(@class, 'cards-group__card-spacing')]//div[contains(@class, 'org-view-entity-card__container')]"
        related_company_containers = driver.find_elements(By.XPATH, primary_container_xpath)
        discovery_source = "primary ('People also follow' or similar sections)"

        if not related_company_containers:
            alternative_container_xpath = "//ul[contains(@class, 'artdeco-list')]//div[contains(@class, 'org-view-entity-card__container')]"
            related_company_containers = driver.find_elements(By.XPATH, alternative_container_xpath)
            discovery_source = "alternative (entity card list)"

        if not related_company_containers:
            print("No related companies found on this page using any fallback method.")
            return

        print(f"Found {len(related_company_containers)} potential related company containers using {discovery_source}.")
        new_slugs_for_queue = set()
        for container in related_company_containers:
            try:
                # Strategy: Skip LinkedIn's auto-generated "Skill Pages".
                try:
                    skill_page_indicator = container.find_element(By.XPATH, ".//span[contains(., 'Page by LinkedIn Skill Pages')]")
                    if skill_page_indicator:
                        continue
                except NoSuchElementException:
                    pass # It's a regular company card.

                link_element = container.find_element(By.XPATH, ".//a[contains(@href, '/company/') or contains(@href, '/showcase/')]")
                href = link_element.get_attribute('href')
                slug = _extract_slug_from_href(href)
                if slug and slug not in scraped_slugs and slug not in discovery_queue:
                    new_slugs_for_queue.add(slug)
            except NoSuchElementException:
                continue # Skip if the card doesn't have the expected structure.
        
        if new_slugs_for_queue:
            discovery_queue.extend(list(new_slugs_for_queue))
            print(f"Added {len(new_slugs_for_queue)} new unique slugs to the discovery queue: {list(new_slugs_for_queue)}")

    except TimeoutException:
        print("Page did not load correctly, cannot find related companies.")
    except Exception as e:
        print(f"An unexpected error occurred during discovery: {e}")

def main():
    """Main execution function for the LinkedIn scraper."""
    all_scraped_data, scraped_slugs = load_existing_data(DATA_FILE)
    scraped_this_run = []
    # Load accounts and proxies
    all_credentials = parse_credentials(CREDENTIALS_FILE)
    all_proxies = load_proxies(PROXIES_FILE)

    if not all_credentials:
        print("No credentials loaded. Exiting.")
        return
    
    # Pair accounts with proxies, cycling through proxies if there are fewer proxies than accounts
    # This master list is created once to ensure pairings are fixed for all cycles.
    if all_proxies:
        master_account_proxy_pairs = list(zip(all_credentials, cycle(all_proxies)))
    else:
        print("No proxies loaded. Running in single IP mode.")
        master_account_proxy_pairs = [(cred, None) for cred in all_credentials]

    discovery_queue = []

    # --- Session State Variables ---
    current_credential = None
    current_proxy = None
    session_scrape_count = 0
    session_limit = 0
    quarantined_in_run = {"accounts": [], "proxies": []}
    stop_script_due_to_network = False

    driver = None
    try:
        print(f"--- Starting discovery loop. Will scrape up to {MAX_NEW_COMPANIES} new companies. ---")
        print(f"--- Scraper will run for a maximum of {MAX_SCRAPE_CYCLES} cycles. ---")

        for cycle_num in range(1, MAX_SCRAPE_CYCLES + 1):
            print("\n" + "#"*60)
            print(f"# Starting Scrape Cycle {cycle_num}/{MAX_SCRAPE_CYCLES}")
            print("#"*60)

            # Create a working copy for this cycle, filtering the master list
            # to exclude any accounts that have been quarantined in previous cycles.
            banned_users = load_blacklist(BANNED_ACCOUNTS_FILE, is_json=True)
            account_proxy_pairs = [
                pair for pair in master_account_proxy_pairs
                if pair[0]['username'] not in banned_users
            ]

            if not account_proxy_pairs:
                print("No active credentials available to start a new cycle. Exiting.")
                break

            # Inner loop processes one full cycle of accounts
            while len(scraped_this_run) < MAX_NEW_COMPANIES and not stop_script_due_to_network:
                current_slug = None # Reset slug for this iteration
                try:
                    # --- Queue Seeding ---
                    if not discovery_queue:
                        print("\nDiscovery queue is empty. Attempting to find a new seed company via search...")
                        if not driver:
                            if not account_proxy_pairs: break # No more accounts in this cycle
                            current_credential, current_proxy = account_proxy_pairs.pop(0)
                            driver, wait = login_and_setup_driver(current_credential, current_proxy)
                            if not driver: continue # Try next account
                            session_scrape_count = 0
                            session_limit = random.randint(COMPANIES_PER_ACCOUNT_RANGE[0], COMPANIES_PER_ACCOUNT_RANGE[1])
                            print(f"--- New session started for seeding. Will scrape up to {session_limit} companies this time. ---")

                        seeded = False
                        for attempt in range(MAX_INDUSTRY_SEARCH_ATTEMPTS):
                            print(f"\n--- Seed attempt {attempt + 1}/{MAX_INDUSTRY_SEARCH_ATTEMPTS} ---")
                            new_slug = find_company_via_search(driver, wait, scraped_slugs, max_pages_to_check=MAX_SEARCH_PAGES_PER_INDUSTRY)
                            if new_slug:
                                discovery_queue.append(new_slug)
                                seeded = True
                                break
                        if not seeded:
                            print(f"\nCould not find any new seed companies after trying {MAX_INDUSTRY_SEARCH_ATTEMPTS} different industries. Ending this cycle.")
                            break # Exit the inner while loop to proceed to the next cycle.

                    # --- Session Management ---
                    if not driver or session_scrape_count >= session_limit:
                        if driver:
                            print(f"\n--- Reached session limit of {session_limit} companies. Switching sessions. ---")
                            driver.quit()

                        if not account_proxy_pairs:
                            print("\n--- Ran out of accounts for this cycle. ---")
                            break
                        
                        current_credential, current_proxy = account_proxy_pairs.pop(0)
                        driver, wait = login_and_setup_driver(current_credential, current_proxy)
                        
                        if not driver:
                            print("Could not establish a new session. Trying next account if available.")
                            continue
                        
                        session_scrape_count = 0
                        session_limit = random.randint(COMPANIES_PER_ACCOUNT_RANGE[0], COMPANIES_PER_ACCOUNT_RANGE[1])
                        print(f"--- New session started. Will scrape up to {session_limit} companies this time. ---")

                    # --- Process a company from the queue ---
                    current_slug = discovery_queue.pop(0)
                    if not current_slug or current_slug in scraped_slugs:
                        continue
                    
                    remaining_to_scrape = MAX_NEW_COMPANIES - len(scraped_this_run)
                    print(f"\n[{len(scraped_this_run) + 1}/{MAX_NEW_COMPANIES}] Processing: {current_slug} ({remaining_to_scrape - 1} more to go)")

                    scrape_success = False
                    for attempt in range(MAX_SCRAPE_RETRIES):
                        try:
                            if not is_logged_in(driver):
                                raise SessionInvalidException("User is logged out.")
                            company_data = scrape_company_data(driver, wait, current_slug)
                            all_scraped_data.append(company_data)
                            scraped_slugs.add(current_slug)
                            scraped_this_run.append(current_slug)
                            session_scrape_count += 1
                            scrape_success = True
                            discover_new_companies(driver, wait, scraped_slugs, discovery_queue, current_slug)
                            perform_curiosity_click(driver, wait)
                            break
                        except SessionInvalidException as e:
                            print(f"!!! Session Error for '{current_slug}': {e}. Forcing session switch. !!!")
                            if current_proxy:
                                print(f"-> Suspected bad proxy: {current_proxy.split('@')[-1]}")
                                quarantine_asset(current_proxy, BAD_PROXIES_FILE)
                                quarantined_in_run["proxies"].append(current_proxy.split('@')[-1])
                            if driver: driver.quit()
                            driver = None
                            discovery_queue.insert(0, current_slug)
                            break
                        except TimeoutException as e:
                            print(f"-> Potential network error on attempt {attempt + 1}/{MAX_SCRAPE_RETRIES} for '{current_slug}': {type(e).__name__}")
                            if attempt == 0:
                                print("-> Pausing for 30 seconds to allow connection to stabilize...")
                                time.sleep(30)
                                print("-> Retrying...")
                            else:
                                print("-> Persistent network issue detected. Stopping script gracefully.")
                                stop_script_due_to_network = True
                                break
                        except NoSuchElementException as e:
                            print(f"-> Page structure error on attempt {attempt + 1}/{MAX_SCRAPE_RETRIES} for '{current_slug}': {type(e).__name__}")
                            if attempt + 1 < MAX_SCRAPE_RETRIES:
                                print("-> Retrying after a short pause...")
                                time.sleep(5)
                            else:
                                print("-> Max retries reached for page structure error. Moving on to the next company.")
                    
                    if not scrape_success and not driver: # If session died during retries
                        continue

                except WebDriverException as e:
                    print(f"\n!!! WebDriver Communication Error: {e} !!!")
                    print("-> This is likely a browser crash or a severe network timeout.")
                    print("-> Discarding current session and attempting to start a new one.")
                    if driver: driver.quit()
                    driver = None
                    if current_slug: discovery_queue.insert(0, current_slug)
                    continue

            # --- Save data at the end of the cycle ---
            save_data(all_scraped_data, DATA_FILE)

            # --- Cycle Cooldown Logic ---
            if cycle_num < MAX_SCRAPE_CYCLES and not stop_script_due_to_network:
                print("\n" + "="*60)
                print(f"Scrape Cycle {cycle_num} complete.")
                print(f"Pausing for {CYCLE_COOLDOWN_MINUTES} minutes before starting the next cycle...")
                print("="*60)
                time.sleep(CYCLE_COOLDOWN_MINUTES * 60)

    except (Exception, KeyboardInterrupt) as e:
        print(f"\nAn unrecoverable error or keyboard interrupt occurred during the process: {e}")

    finally:
        if driver:
            print("Closing the browser.")
            driver.quit()

        # --- Save data and print summary regardless of how the script exits ---
        if scraped_this_run:
            print("\n" + "="*25 + "\n--- Scraping Summary ---\n" + "="*25)
            print(f"Total new companies scraped: {len(scraped_this_run)}")
        else:
            print("\n--- Scraping Summary for This Run ---")
            print("No new companies were scraped in this session.")
        
        if quarantined_in_run["accounts"] or quarantined_in_run["proxies"]:
            print("\n--- Quarantine Report for This Run ---")
            if quarantined_in_run["accounts"]:
                print(f"Quarantined Accounts: {quarantined_in_run['accounts']}")
            if quarantined_in_run["proxies"]:
                print(f"Quarantined Proxies: {quarantined_in_run['proxies']}")
        
        print("------------------------------------")

        save_data(all_scraped_data, DATA_FILE)

if __name__ == "__main__":
    main()
