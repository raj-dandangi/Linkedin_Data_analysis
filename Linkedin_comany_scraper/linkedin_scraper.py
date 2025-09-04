import time
import json
import os
import random
import re
import zipfile
from itertools import cycle
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.action_chains import ActionChains
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

# --- Configuration ---
MAX_NEW_COMPANIES = 50000
COMPANIES_PER_ACCOUNT_RANGE =(2500,5000)
MAX_SEARCH_PAGES_PER_INDUSTRY = 50

# --- File Paths ---
CREDENTIALS_FILE = "credentials.json"
PROXIES_FILE = "proxies.txt"
DATA_FILE = "scraped_data.json"
BANNED_ACCOUNTS_FILE = "banned_accounts.json"
BAD_PROXIES_FILE = "bad_proxies.txt"

WAIT_TIME = 30

PRIORITY_INDUSTRIES = [
    "Software Development", "IT Services and IT Consulting", "Technology, Information and Internet",
    "Entertainment Providers", "Financial Services", "Computer Hardware Manufacturing",
    "Research Services", "Banking", "Translation and Localization", "Biotechnology Research"
]

# --- Custom Exception for session-killing errors ---
class SessionInvalidException(Exception):
    """Custom exception for when a session (account/proxy) is no longer valid."""
    pass

#<editor-fold desc="Data Loading and Management Functions"> 

def load_blacklist(file_path, is_json=False):
    if not os.path.exists(file_path):
        return set()
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            if is_json:
                return {item['username'] for item in json.load(f)}
            return {line.strip() for line in f if line.strip()}
    except (IOError, json.JSONDecodeError):
        return set()

def load_existing_data(file_path):
    if not os.path.exists(file_path):
        return [], set()
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data, {item.get('company_slug') for item in data if item.get('company_slug')}
    except (json.JSONDecodeError, IOError):
        return [], set()

def quarantine_asset(asset, file_path, is_json=False):
    print(f"--- QUARANTINING ASSET -> {file_path} ---")
    try:
        items = []
        if is_json:
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    try: items = json.load(f)
                    except json.JSONDecodeError: pass
            items.append(asset)
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(items, f, indent=2)
        else:
            with open(file_path, 'a', encoding='utf-8') as f:
                f.write(str(asset) + '\n')
    except IOError as e:
        print(f"!!! Could not write to quarantine file {file_path}: {e} !!!")

def parse_credentials(file_path):
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
    bad_proxies = load_blacklist(BAD_PROXIES_FILE)
    if not os.path.exists(file_path):
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
#</editor-fold>

#<editor-fold desc="Human-like Browser Interaction Functions"> 

def human_like_typing(element, text):
    for char in text:
        element.send_keys(char)
        time.sleep(random.uniform(0.05, 0.2))

def human_like_click(driver, element):
    try:
        ActionChains(driver).move_to_element(element).pause(random.uniform(0.3, 0.8)).click().perform()
    except Exception as e:
        print(f"Could not perform human-like click, falling back to JS click. Error: {e}")
        driver.execute_script("arguments[0].click();", element)

def human_like_scroll(driver):
    try:
        total_height = driver.execute_script("return document.body.scrollHeight")
        if total_height < 1500: return
        current_position = 0
        while current_position < total_height * random.uniform(0.7, 1.0):
            scroll_increment = max(200, min(random.randint(int((total_height - current_position) * 0.2), int((total_height - current_position) * 0.5)), 900))
            driver.execute_script(f"window.scrollBy(0, {scroll_increment});")
            time.sleep(random.uniform(0.4, 1.0) + (current_position / total_height))
            if random.random() < 0.15:
                driver.execute_script(f"window.scrollBy(0, -{random.randint(100, 400)});")
                time.sleep(random.uniform(0.7, 1.6))
            new_position = driver.execute_script("return window.pageYOffset;")
            if new_position == current_position: break
            current_position = new_position
    except Exception as e:
        print(f"Could not perform human-like scroll: {e}")

def perform_curiosity_click(driver, wait):
    if random.random() > 0.15: return
    print("--- Performing a 'curiosity' click... ---")
    try:
        footer_links = driver.find_elements(By.XPATH, "//footer//a[contains(@href, 'linkedin.com/legal') or contains(@href, 'linkedin.com/about')]")
        if footer_links:
            human_like_click(driver, random.choice(footer_links))
            time.sleep(random.uniform(3, 6))
            driver.back()
            wait.until(EC.presence_of_element_located((By.ID, "global-nav-search")))
    except Exception as e:
        print(f"Could not perform curiosity click: {e}")
#</editor-fold>

#<editor-fold desc="Core Scraping and Discovery Functions"> 

def scrape_company_data(driver, wait, company_slug):
    scraped_data = {"company_slug": company_slug}
    about_url = f"https://www.linkedin.com/company/{company_slug}/about/"
    print(f"\n--- Scraping Company: {company_slug} ---")
    driver.get(about_url)
    check_for_session_errors(driver)
    human_like_scroll(driver)
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".org-top-card")))
    try:
        followers_element = wait.until(EC.presence_of_element_located((By.XPATH, "//a[contains(@href, '/followers/')] ")))
        scraped_data["followers"] = followers_element.text.strip()
    except TimeoutException: pass
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "dl")))
    try:
        description_element = wait.until(EC.presence_of_element_located((By.XPATH, "//h2[normalize-space(.)='Overview']/following-sibling::p")))
        scraped_data["overview"] = description_element.text.strip()
    except TimeoutException: pass
    details_to_scrape = {"website": "Website", "industry": "Industry", "company_size": "Company size", "headquarters": "Headquarters"}
    for key, label in details_to_scrape.items():
        try:
            element = wait.until(EC.presence_of_element_located((By.XPATH, f"//dt[normalize-space(.)='{label}']/following-sibling::dd[1]")))
            scraped_data[key] = element.text.strip().split('\n')[0]
        except TimeoutException: pass
    time.sleep(random.uniform(2.5, 5.5))
    jobs_url = f"https://www.linkedin.com/company/{company_slug}/jobs/"
    driver.get(jobs_url)
    check_for_session_errors(driver)
    try:
        job_count_element = wait.until(EC.presence_of_element_located((By.XPATH, "//*[self::h1 or self::h2 or self::h3 or self::h4][contains(., 'job') or contains(., 'result')]")))
        scraped_data['job_openings_text'] = job_count_element.text.strip()
    except TimeoutException: pass
    driver.get(about_url)
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "dl")))
    return scraped_data

def find_first_new_company_on_page(driver, wait, search_term, page_num, scraped_slugs):
    print(f"\n--- Searching for '{search_term}' on page {page_num}... ---")
    search_url = f"https://www.linkedin.com/search/results/companies/?keywords={search_term}&page={page_num}"
    driver.get(search_url)
    check_for_session_errors(driver)
    try:
        wait.until(EC.presence_of_element_located((By.XPATH, "//div[contains(@class, 'search-results-container')]")))
        human_like_scroll(driver)
    except TimeoutException:
        print(f"Timed out waiting for search results container to load.")
        return None
    company_containers = driver.find_elements(By.XPATH, "//div[@data-chameleon-result-urn]")
    if not company_containers:
        print("No company result containers found on this page.")
        return None
    print(f"Found {len(company_containers)} company containers on page. Analyzing for new slugs...")
    for container in company_containers:
        try:
            try:
                if container.find_element(By.XPATH, ".//span[contains(., 'Page by LinkedIn Skill Pages')]"):
                    continue
            except NoSuchElementException:
                pass
            title_link_element = container.find_element(By.XPATH, ".//span[contains(@class, 't-16')]/a[contains(@href, '/company/')] ")
            href = title_link_element.get_attribute('href')
            slug = _extract_slug_from_href(href)
            if slug and slug not in scraped_slugs:
                print(f"*** Found new seed company: '{slug}' ***")
                return slug
        except (NoSuchElementException, IndexError):
            continue
    print("No new, unscraped companies found on this page.")
    return None

def _extract_slug_from_href(href):
    if not href: return None
    match = re.search(r'/(?:company|showcase)/([^/?]+)', href)
    return match.group(1) if match else None

def discover_new_companies(driver, wait, scraped_slugs, discovery_queue, current_slug):
    print(f"\n--- Discovering new companies from '{current_slug}' ---")
    new_slugs_for_queue = set()
    try:
        all_links = driver.find_elements(By.TAG_NAME, "a")
        for link in all_links:
            try:
                href = link.get_attribute('href')
                slug = _extract_slug_from_href(href)
                if slug and slug != current_slug and slug not in scraped_slugs and slug not in discovery_queue:
                    new_slugs_for_queue.add(slug)
            except Exception: continue
        if new_slugs_for_queue:
            slug_list = list(new_slugs_for_queue)
            discovery_queue[0:0] = slug_list
            print(f"+++ Added {len(slug_list)} new slugs to the front of the discovery queue. +++")
        else:
            print("No new, unique companies found on this page.")
    except (WebDriverException, TimeoutException) as e:
        print(f"An error occurred during company discovery: {e}")
        if isinstance(e, WebDriverException): raise SessionInvalidException(f"WebDriver error during discovery: {e}")
#</editor-fold>

#<editor-fold desc="Session Management Functions"> 

def check_for_session_errors(driver):
    page_title = driver.title.lower()
    if "security check" in page_title or "prove you're human" in driver.page_source.lower():
        raise SessionInvalidException("CAPTCHA detected")
    if "access denied" in page_title:
        raise SessionInvalidException("Access Denied")

def is_logged_in(driver):
    try:
        driver.find_element(By.ID, "global-nav-search")
        return True
    except (NoSuchElementException, TimeoutException):
        return False

def login_and_setup_driver(credential, proxy=None):
    print(f"\n---\nAttempting to log in with account: {credential['username']}")
    if proxy: print(f"Using proxy: {proxy.split('@')[-1]}")
    
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
            mode: \"fixed_servers\",
            rules: {{
                singleProxy: {{
                    scheme: \"http\",
                    host: \"{proxy_host}\",
                    port: parseInt({proxy_port})
                }},
                bypassList: [\"localhost\"]
            }}
        }};
        chrome.proxy.settings.set({{value: config, scope: \"regular\"}}, function() {{}}); 
        function callbackFn(details) {{
            return {{
                authCredentials: {{
                    username: \"{proxy_user}\",
                    password: \"{proxy_pass}\"
                }}
            }};
        }}
        chrome.webRequest.onAuthRequired.addListener(callbackFn, {{urls: [\"<all_urls>\"]}}, [\'blocking\']);
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
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    chrome_options.add_argument(f"user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=chrome_options)
    driver.set_page_load_timeout(300) # 5 minutes
    
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    wait = WebDriverWait(driver, WAIT_TIME)
    
    safe_username = ''.join(c for c in credential['username'] if c.isalnum())
    cookie_file = f"linkedin_cookies_{safe_username}.json"
    
    logged_in = False
    if os.path.exists(cookie_file):
        try:
            print("Attempting to log in via cookies...")
            driver.get("https://www.linkedin.com")
            with open(cookie_file, 'r') as f: cookies = json.load(f)
            for cookie in cookies: driver.add_cookie(cookie)
            driver.get("https://www.linkedin.com/feed/")
            wait.until(EC.presence_of_element_located((By.ID, "global-nav-search")))
            print("Successfully logged in using cookies.")
            logged_in = True
        except Exception as e:
            print(f"Cookie-based login failed: {e}")
            if os.path.exists(cookie_file):
                os.remove(cookie_file)
            
    if not logged_in:
        try:
            print("Attempting to log in via credentials...")
            driver.get("https://www.linkedin.com/login")
            username_field = wait.until(EC.presence_of_element_located((By.ID, "username")))
            human_like_typing(username_field, credential['username'])
            password_field = driver.find_element(By.ID, "password")
            human_like_typing(password_field, credential['password'])
            password_field.send_keys(Keys.RETURN)
            wait.until(EC.presence_of_element_located((By.ID, "global-nav-search")))
            print("Login successful.")
            logged_in = True
            with open(cookie_file, "w") as f: json.dump(driver.get_cookies(), f)
        except (TimeoutException, WebDriverException) as e:
            print(f"!!! LOGIN FAILED for {credential['username']}: {e} !!!")
            quarantine_asset(credential, BANNED_ACCOUNTS_FILE, is_json=True)
            driver.quit()
            time.sleep(2)
            return None, None
            
    return driver, wait

#</editor-fold>

def main():
    """Main execution function for the LinkedIn scraper."""
    all_scraped_data, scraped_slugs = load_existing_data(DATA_FILE)
    scraped_this_run = []
    all_credentials = parse_credentials(CREDENTIALS_FILE)
    all_proxies = load_proxies(PROXIES_FILE)
    if not all_credentials: return
    master_account_proxy_pairs = list(zip(all_credentials, cycle(all_proxies))) if all_proxies else [(c, None) for c in all_credentials]
    
    # --- Global State for the entire run ---
    discovery_queue = []
    search_industries = list(PRIORITY_INDUSTRIES)
    random.shuffle(search_industries)
    current_industry_index = 0
    search_page_num = 1
    
    # --- Session State ---
    driver, wait = None, None
    session_scrape_count = 0
    session_limit = 0
    quarantined_in_run = {"accounts": [], "proxies": []}
    current_credential = None

    print(f"--- Starting dynamic scraping loop. Will scrape up to {MAX_NEW_COMPANIES} new companies. ---")
    account_cycler = cycle(master_account_proxy_pairs)

    try:
        while len(scraped_this_run) < MAX_NEW_COMPANIES:
            try:
                if not driver or session_scrape_count >= session_limit:
                    if driver: driver.quit()
                    current_credential, current_proxy = next(account_cycler)
                    if current_credential['username'] in load_blacklist(BANNED_ACCOUNTS_FILE, is_json=True):
                        continue
                    driver, wait = login_and_setup_driver(current_credential, current_proxy)
                    if not driver:
                        quarantined_in_run["accounts"].append(current_credential['username'])
                        continue
                    session_scrape_count = 0
                    session_limit = random.randint(*COMPANIES_PER_ACCOUNT_RANGE)
                    print(f"--- New session for {current_credential['username']}. Limit: {session_limit} scrapes. ---")

                current_slug = None
                if discovery_queue:
                    current_slug = discovery_queue.pop(0)
                    if current_slug in scraped_slugs: continue
                else:
                    if current_industry_index >= len(search_industries):
                        print("\n--- All priority industries have been searched. Ending script. ---")
                        break
                    
                    current_industry = search_industries[current_industry_index]
                    
                    if search_page_num > MAX_SEARCH_PAGES_PER_INDUSTRY:
                        print(f"\n--- Finished searching '{current_industry}'. Moving to next industry. ---")
                        current_industry_index += 1
                        search_page_num = 1
                        continue

                    current_slug = find_first_new_company_on_page(driver, wait, current_industry, search_page_num, scraped_slugs)
                    
                    search_page_num += 1
                    if not current_slug:
                        continue

                print(f"\n[{len(scraped_this_run) + 1}/{MAX_NEW_COMPANIES}] Processing: {current_slug} (Session: {session_scrape_count + 1}/{session_limit})")
                company_data = scrape_company_data(driver, wait, current_slug)
                all_scraped_data.append(company_data)
                scraped_slugs.add(current_slug)
                scraped_this_run.append(current_slug)
                session_scrape_count += 1
                
                discover_new_companies(driver, wait, scraped_slugs, discovery_queue, current_slug)
                perform_curiosity_click(driver, wait)
                time.sleep(random.uniform(2.5, 5.5))

            except SessionInvalidException as e:
                print(f"!!! SESSION ERROR for {current_credential['username']}: {e}. Switching session. !!!")
                if current_proxy and str(current_proxy) not in quarantined_in_run["proxies"]:
                    quarantine_asset(current_proxy, BAD_PROXIES_FILE)
                    quarantined_in_run["proxies"].append(str(current_proxy))
                if current_slug: discovery_queue.insert(0, current_slug)
                if driver: driver.quit()
                driver = None
            except (TimeoutException, NoSuchElementException, WebDriverException) as e:
                print(f"-> RECOVERABLE ERROR for '{current_slug}': {type(e).__name__}. Re-queuing and switching session.")
                if current_slug: discovery_queue.insert(0, current_slug)
                if driver: driver.quit()
                driver = None

    except (Exception, KeyboardInterrupt) as e:
        print(f"\nAn unrecoverable error or keyboard interrupt occurred: {e}")

    finally:
        if driver: driver.quit()
        print("\n" + "="*25 + "\n--- SCRAPING SUMMARY ---" + "\n" + "="*25)
        print(f"Total new companies scraped: {len(scraped_this_run)}")
        if quarantined_in_run["accounts"] or quarantined_in_run["proxies"]:
            print("\n--- QUARANTINE REPORT ---")
            if quarantined_in_run["accounts"]: print(f"Quarantined Accounts: {quarantined_in_run['accounts']}")
            if quarantined_in_run["proxies"]: print(f"Quarantined Proxies: {quarantined_in_run['proxies']}")
        if all_scraped_data:
            print(f"\nSaving {len(all_scraped_data)} total companies to '{DATA_FILE}'...")
            try:
                with open(DATA_FILE, "w", encoding='utf-8') as f:
                    json.dump(all_scraped_data, f, indent=2, ensure_ascii=False)
                print(f"Data successfully saved to '{DATA_FILE}'")
            except IOError as e:
                print(f"!!! CRITICAL: Could not save data to file: {e} !!!")

if __name__ == "__main__":
    main()
