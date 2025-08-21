🌐 LinkedIn Company Data Scraper

> **A robust, human-like Python scraper for collecting public company data from LinkedIn at scale.**

---

## 🔍 Overview

The **LinkedIn Company Data Scraper** is a production-grade web scraping tool built with **Python and Selenium** to autonomously extract public company information from LinkedIn while mimicking natural user behavior. Designed for resilience and long-term operation, it avoids detection through intelligent automation patterns, session management, and distributed account usage.

This scraper is ideal for market research, lead generation, competitive intelligence, and organizational analysis — all while adhering to ethical scraping practices and minimizing the risk of IP or account bans.

---

## 🚀 Key Features

✅ **Multi-Account & Proxy Rotation**  
Distributes requests across multiple LinkedIn accounts and proxy servers to reduce detection risk and maximize uptime.

✅ **Persistent Session Management**  
Saves and reuses login cookies to bypass repeated authentication, speeding up session startups and reducing login triggers.

✅ **Organic Discovery Engine**  
- **Seeding**: Automatically finds seed companies using high-priority industries when the queue is empty.  
- **Discovery**: Expands the scrape queue by extracting related companies from “People also viewed” and “Recommended pages” sections.

✅ **Human-Like Browsing Behavior**  
Simulates realistic user interactions:
- Randomized delays between actions
- Natural scrolling
- Occasional "curiosity clicks" on footer links

✅ **Advanced Resilience & Error Handling**
- Detects CAPTCHAs, access denials, and forced logouts
- Quarantines faulty accounts/proxies automatically
- Recovers from browser crashes and network timeouts
- Retries failed scrapes with exponential backoff logic

✅ **Intelligent Filtering**  
Skips auto-generated LinkedIn Skill or Topic pages — only scrapes real company profiles.

✅ **Multi-Cycle Operation**  
Supports multiple scraping cycles with configurable cooldowns between runs for stealthy, long-duration operations.

✅ **Periodic Data Persistence**  
Saves scraped data to `scraped_data.json` after every cycle to prevent data loss during extended runs.

✅ **Automated Quarantine System**  
Maintains logs of banned accounts (`banned_accounts.json`) and bad proxies (`bad_proxies.txt`) to avoid reuse in future cycles.

---

## ⚙️ How It Works: The Scraping Workflow

### 1. **Initialization**
- Loads previously scraped data to avoid duplicates
- Reads credentials from `credentials.json`
- Loads proxies from `proxies.txt`
- Filters out quarantined accounts/proxies
- Builds persistent account-proxy pairings for consistency

### 2. **Main Cycle Loop**
Runs for a configurable number of cycles (`MAX_SCRAPE_CYCLES`). Each cycle:
- Refreshes active account list (excluding quarantined ones)
- Processes each account in sequence

### 3. **Per-Account Session**
For each account:
- Uses saved cookies for fast login (falls back to credentials if needed)
- Assigns a random scrape limit per session
- Begins processing the discovery queue

### 4. **Scraping & Discovery Loop**
#### ➤ Queue Check (Seeding Mode)
If no companies are queued:
- Searches a random industry from `PRIORITY_INDUSTRIES`
- Adds the first valid unscraped company to the queue

#### ➤ Processing a Company
- Navigates to **Company About** and **Jobs** pages
- Extracts structured data:
  - Name, Overview, Industry, Size
  - Headquarters, Website, Follow Count
  - Job postings (title, location, date posted)

#### ➤ Discovery Phase
After scraping:
- Parses “People also viewed” and “Recommended pages”
- Adds new, unscraped company slugs to the end of the queue

Loop continues until session limit reached or session invalidated.

### 5. **Cooldown & Repeat**
- After completing all accounts in a cycle:
  - Saves all data
  - Waits for `CYCLE_COOLDOWN_MINUTES`
  - Starts next cycle

### 6. **Graceful Shutdown**
On completion or critical error:
- Final save of scraped data
- Logs summary of quarantined accounts/proxies
- Closes browser cleanly

---

## 🔧 Configuration

All settings are defined at the top of `linkedin_scraper.py`:

| Parameter | Description |
|--------|-------------|
| `MAX_SCRAPE_CYCLES` | Number of full cycles through all accounts |
| `CYCLE_COOLDOWN_MINUTES` | Minutes to wait between cycles |
| `MAX_NEW_COMPANIES` | Total number of new companies to scrape before stopping |
| `COMPANIES_PER_ACCOUNT_RANGE` | Min/max companies scraped per session (e.g., `(30, 70)`) |
| `MAX_SCRAPE_RETRIES` | Retry attempts per company on recoverable errors |
| `MAX_INDUSTRY_SEARCH_ATTEMPTS` | Max industries to try during seeding |
| `PRIORITY_INDUSTRIES` | List of industry keywords for seed discovery |

---

## 📁 File Structure

### 📌 Input Files (You Provide)
| File | Format | Purpose |
|------|--------|--------|
| `credentials.json` | JSON array of `{ "username": "...", "password": "..." }` | Login credentials for multiple LinkedIn accounts |
| `proxies.txt` | One line per proxy: `host:port:username:password` | Rotating proxy list for IP diversity |

### 💾 Output Files (Auto-Generated)
| File | Purpose |
|------|--------|
| `scraped_data.json` | Master dataset of all scraped company info |
| `banned_accounts.json` | Accounts that failed login and were blacklisted |
| `bad_proxies.txt` | Proxies that caused session errors |
| `linkedin_cookies_<user>.json` | Saved session cookies for faster re-login |

---

## ▶️ How to Run

### Prerequisites
```bash
pip install selenium webdriver-manager
```

> Ensure Chrome is installed on your system (used via ChromeDriver).

### Steps
1. Create your input files:
   - `credentials.json` – list of LinkedIn accounts
   - `proxies.txt` – one proxy per line (optional but recommended)

2. Customize configuration values in `linkedin_scraper.py`

3. Run the scraper:
```bash
python linkedin_scraper.py
```

> The script will launch a browser instance, log in, and begin collecting data.

---


## ⚠️ Ethical Use Notice

This tool is designed to scrape **publicly available data** in a **responsible, non-disruptive manner**. Always:
- Respect `robots.txt` and LinkedIn’s Terms of Service
- Avoid aggressive scraping rates
- Use proxies and delays to minimize impact
- Do not use for spam, phishing, or unauthorized data harvesting

> **Note**: LinkedIn actively detects and blocks automated access. Use this tool cautiously and consider legal implications in your jurisdiction.



**Built with ❤️ for data-driven insights — ethically and efficiently.**  
*Perfect for researchers, analysts, and growth teams.*
