#!/usr/bin/env python3
"""
Benchmark Scientific product scraper  ->  CSV

Flow:
  1. Open the home page and read the "Products" menu to find every category link
     (/product-category/...).  External links (Hermle, Accuris, ...) are skipped.
  2. Walk each category page (with pagination) and collect product URLs.
  3. Open every product page and extract its data.
  4. Save one CSV row per product.

Usage:
    pip install requests beautifulsoup4
    python benchmark_scraper.py                              # everything
    python benchmark_scraper.py --category vortex-mixers     # one category
    python benchmark_scraper.py --max-products 5             # quick test run
"""

import argparse
import csv
import json
import logging
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.benchmarkscientific.com/"
HOST = urlparse(BASE_URL).netloc
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": BASE_URL,
    "Upgrade-Insecure-Requests": "1",
}
_browser = {"page": None}   # filled when --browser is used
DELAY = 1.0      # seconds between requests - be polite
TIMEOUT = 20
RETRIES = 3

CSV_COLUMNS = [
    "sku", "name", "price", "currency", "categories", "short_description",
    "description", "specifications", "specifications_json", "accessories",
    "documents", "image_url", "product_url", "scraped_at",
]

log = logging.getLogger("benchmark")


# ----------------------------------------------------------------------------
# HTTP helpers
# ----------------------------------------------------------------------------
def fetch(session, url):
    for attempt in range(1, RETRIES + 1):
        try:
            if _browser["page"] is not None:                 # real-browser mode
                resp = _browser["page"].goto(url, wait_until="domcontentloaded", timeout=45000)
                if resp is not None and resp.status == 404:
                    log.warning("404: %s", url)
                    return None
                if resp is not None and resp.status >= 400:
                    raise requests.RequestException(f"HTTP {resp.status}")
                return BeautifulSoup(_browser["page"].content(), "html.parser")
            r = session.get(url, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code == 404:
                log.warning("404: %s", url)
                return None
            r.raise_for_status()
            return BeautifulSoup(r.text, "html.parser")
        except requests.RequestException as exc:
            log.warning("Attempt %d/%d failed for %s: %s", attempt, RETRIES, url, exc)
            if "403" in str(exc) and _browser["page"] is None:
                log.warning("403 = the server is blocking plain requests. "
                            "Try:  python benchmark_scraper.py --browser")
            time.sleep(attempt * 2)
        except Exception as exc:                             # playwright errors
            log.warning("Attempt %d/%d failed for %s: %s", attempt, RETRIES, url, exc)
            time.sleep(attempt * 2)
    log.error("Giving up on %s", url)
    return None


_robots = {}


def allowed_by_robots(url):
    """Fetch robots.txt ourselves (urllib's parser treats a 403 as 'disallow all')."""
    if "rp" not in _robots:
        rp = RobotFileParser()
        try:
            r = requests.get(urljoin(BASE_URL, "/robots.txt"), headers=HEADERS, timeout=TIMEOUT)
            if r.status_code == 200:
                rp.parse(r.text.splitlines())
            else:
                rp.parse([])            # no usable robots.txt -> allow
        except requests.RequestException:
            rp.parse([])
        _robots["rp"] = rp
    return _robots["rp"].can_fetch("*", url)


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def same_site(url):
    return urlparse(url).netloc.replace("www.", "") == HOST.replace("www.", "")


# ----------------------------------------------------------------------------
# Step 1 + 2: categories and product URLs
# ----------------------------------------------------------------------------
def get_category_urls(session):
    """Read the 'Products' dropdown on the home page."""
    soup = fetch(session, BASE_URL)
    if soup is None:
        return []
    urls = []
    for a in soup.select('a[href*="/product-category/"]'):
        url = urljoin(BASE_URL, a["href"]).split("#")[0]
        if same_site(url) and url not in urls:
            urls.append(url)
    return urls


def get_product_urls(session, category_url):
    """Collect product links from a category, following pagination."""
    found, page_url = [], category_url
    while page_url:
        soup = fetch(session, page_url)
        if soup is None:
            break
        links = soup.select("li.product a.woocommerce-LoopProduct-link") or \
                soup.select('ul.products a[href*="/product/"]')
        for a in links:
            url = urljoin(page_url, a["href"]).split("#")[0]
            if "/product/" in url and url not in found:
                found.append(url)
        nxt = soup.select_one("a.next.page-numbers")
        page_url = urljoin(page_url, nxt["href"]) if nxt else None
        time.sleep(DELAY)
    return found


# ----------------------------------------------------------------------------
# Step 3: product page parsing
# ----------------------------------------------------------------------------
def heading(soup, keyword):
    for h in soup.find_all(["h2", "h3", "h4"]):
        if keyword.lower() in clean(h.get_text()).lower():
            return h
    return None


def split_price(raw):
    m = re.search(r"([^\d\s.,-]*)\s*([\d][\d.,]*)", raw or "")
    return (m.group(2).replace(",", ""), m.group(1)) if m else ("", "")


def parse_product(soup, url):
    row = {c: "" for c in CSV_COLUMNS}
    row["product_url"] = url
    row["scraped_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # name / sku
    el = soup.select_one("h1.product_title") or soup.find("h1")
    row["name"] = clean(el.get_text()) if el else ""
    el = soup.select_one("span.sku")
    row["sku"] = clean(el.get_text()) if el else ""

    # price (some items are quote-only and have none)
    el = soup.select_one("p.price .woocommerce-Price-amount, .summary .price")
    price, currency = split_price(clean(el.get_text()) if el else "")
    row["price"], row["currency"] = price, currency

    # categories
    cats = [clean(a.get_text()) for a in soup.select(".posted_in a")]
    row["categories"] = " | ".join(cats)

    # short description (bullet list under the price)
    el = soup.select_one(".woocommerce-product-details__short-description")
    if el:
        items = [clean(li.get_text()) for li in el.find_all("li")]
        row["short_description"] = " | ".join(items) if items else clean(el.get_text())

    # long description
    el = soup.select_one("#tab-description, .woocommerce-Tabs-panel--description")
    if el:
        row["description"] = clean(el.get_text())
    else:
        meta = soup.find("meta", attrs={"name": "description"}) or \
               soup.find("meta", property="og:description")
        row["description"] = clean(meta.get("content", "")) if meta else ""

    # main image
    a = soup.select_one(".woocommerce-product-gallery__image a")
    img = soup.select_one(".woocommerce-product-gallery__image img")
    if a and a.get("href"):
        row["image_url"] = urljoin(url, a["href"])
    elif img:
        row["image_url"] = urljoin(url, img.get("data-large_image") or img.get("src", ""))

    # specifications table
    specs = {}
    h = heading(soup, "Specification")
    table = h.find_next("table") if h else soup.select_one("table.woocommerce-product-attributes")
    if table:
        for tr in table.find_all("tr"):
            cells = [clean(c.get_text()) for c in tr.find_all(["th", "td"])]
            if len(cells) >= 2 and cells[0]:
                specs[cells[0].rstrip(":")] = cells[1]
    row["specifications"] = "; ".join(f"{k}: {v}" for k, v in specs.items())
    row["specifications_json"] = json.dumps(specs, ensure_ascii=False)

    # optional accessories (SKUs / names)
    h = heading(soup, "Optional Accessories")
    if h:
        ul = h.find_next("ul")
        if ul:
            names = []
            for li in ul.find_all("li", recursive=False):
                link = li.find("a")
                if link:
                    names.append(clean(link.get_text()).replace("Placeholder ", ""))
            row["accessories"] = " | ".join(n for n in names if n)

    # documents (brochures / PDFs)
    docs = []
    h = heading(soup, "Links and Documents")
    scope = h.find_next("ul") if h else None
    for a in (scope or soup).select('a[href$=".pdf"]'):
        docs.append(urljoin(url, a["href"]))
    row["documents"] = " | ".join(dict.fromkeys(docs))

    return row


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Scrape benchmarkscientific.com products to CSV")
    ap.add_argument("--out", default="benchmark_products.csv")
    ap.add_argument("--category", help="Only this category slug, e.g. vortex-mixers")
    ap.add_argument("--max-products", type=int, help="Stop after N products (testing)")
    ap.add_argument("--browser", action="store_true",
                    help="Use a real Chromium browser (needs: pip install playwright && playwright install chromium)")
    ap.add_argument("--ignore-robots", action="store_true", help="Skip robots.txt check")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    session = requests.Session()

    pw = browser = None
    if args.browser:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=HEADERS["User-Agent"], locale="en-US")
        _browser["page"] = ctx.new_page()

    categories = get_category_urls(session)
    if args.category:
        categories = [c for c in categories if f"/product-category/{args.category}" in c]
    log.info("Found %d categories", len(categories))

    product_urls = []
    for cat in categories:
        if not args.ignore_robots and not allowed_by_robots(cat):
            log.warning("robots.txt disallows %s - skipped", cat)
            continue
        urls = get_product_urls(session, cat)
        log.info("%s -> %d products", cat, len(urls))
        for u in urls:
            if u not in product_urls:
                product_urls.append(u)

    if args.max_products:
        product_urls = product_urls[: args.max_products]
    log.info("Scraping %d unique product pages", len(product_urls))

    rows = []
    for i, url in enumerate(product_urls, 1):
        soup = fetch(session, url)
        if soup is None:
            continue
        row = parse_product(soup, url)
        rows.append(row)
        log.info("[%d/%d] %s  %s", i, len(product_urls), row["sku"], row["name"])
        time.sleep(DELAY)

        # save progress regularly so a crash doesn't lose everything
        if i % 25 == 0:
            save_csv(rows, args.out)

    save_csv(rows, args.out)
    if browser:
        browser.close()
        pw.stop()


def save_csv(rows, path):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    log.info("Saved %d rows -> %s", len(rows), path)


if __name__ == "__main__":
    main()