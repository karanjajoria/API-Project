#!/usr/bin/env python3
"""
Scrape all products from https://www.benchmarkscientific.com/ into an Excel file.

Output layout
-------------
* One worksheet per product category (the "types" in the Products menu).
* One row per product.
* One column per detail (name, SKU, price, features, every row of the
  Specifications table, accessories, documents, ...).  Spec columns are the
  union of all spec labels found in that category, so each sheet only has
  the columns that are relevant to it.

Install:
    pip install requests beautifulsoup4 lxml openpyxl curl_cffi
    # optional, only if curl_cffi is still blocked (403):
    pip install playwright && playwright install chromium

Run:
    python scrape_benchmarkscientific.py
    python scrape_benchmarkscientific.py --output products.xlsx --workers 4 --delay 0.5
    python scrape_benchmarkscientific.py --only vortex-mixers --only agarose   # test run
    python scrape_benchmarkscientific.py --engine playwright                   # real browser
"""

from __future__ import annotations

import argparse
import re
import sys
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = "https://www.benchmarkscientific.com/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Columns that always come first on every sheet (in this order).
FIXED_COLUMNS = [
    "Category",
    "Product Name",
    "SKU",
    "Price",
    "Features",
    "Short Description",
    "Description",
    "Group Items",
    "Optional Accessories",
    "Documents",
    "Image URL",
    "Product URL",
]

ILLEGAL_XML_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


# --------------------------------------------------------------------------- #
# HTTP helpers  (3 engines, because the site's firewall blocks plain `requests`)
#   curl_cffi  : impersonates a real Chrome TLS fingerprint  (default if installed)
#   requests   : plain python-requests                        (often gets 403)
#   playwright : drives a real Chromium browser               (slowest, most reliable)
# --------------------------------------------------------------------------- #
ENGINE = "auto"
HEADED = False
_PW_STATE: dict = {}
_PW_LOCK = threading.Lock()

BROWSER_HEADERS = {
    **HEADERS,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}


def resolve_engine(engine: str) -> str:
    if engine != "auto":
        return engine
    try:
        import curl_cffi  # noqa: F401
        return "curl_cffi"
    except ImportError:
        return "requests"


class HttpError(RuntimeError):
    pass


class Fetcher:
    def __init__(self, engine: str):
        self.engine = engine
        self.session = None
        if engine == "curl_cffi":
            from curl_cffi import requests as cr
            self.session = cr.Session(impersonate="chrome")
        elif engine == "requests":
            s = requests.Session()
            s.headers.update(BROWSER_HEADERS)
            retry = Retry(total=3, backoff_factor=1.0, status_forcelist=(429, 500, 502, 503, 504))
            s.mount("https://", HTTPAdapter(max_retries=retry))
            self.session = s

    def _playwright_get(self, url: str) -> str:
        with _PW_LOCK:  # one shared browser, pages fetched one at a time
            if "page" not in _PW_STATE:
                from playwright.sync_api import sync_playwright
                pw = sync_playwright().start()
                browser = pw.chromium.launch(headless=not HEADED)
                ctx = browser.new_context(user_agent=HEADERS["User-Agent"], locale="en-US")
                _PW_STATE.update(pw=pw, browser=browser, page=ctx.new_page())
            page = _PW_STATE["page"]
            resp = page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(1500)  # let any JS challenge finish
            if resp is not None and resp.status >= 400:
                raise HttpError(f"{resp.status} for {url}")
            return page.content()

    def get_html(self, url: str) -> str:
        if self.engine == "playwright":
            return self._playwright_get(url)
        last = None
        for attempt in range(4):
            r = self.session.get(url, headers=BROWSER_HEADERS if self.engine == "curl_cffi" else None, timeout=30)
            if r.status_code == 200:
                return r.text
            last = r.status_code
            time.sleep(1.5 * (attempt + 1))
        raise HttpError(f"HTTP {last} for {url}")


def make_session() -> Fetcher:
    return Fetcher(resolve_engine(ENGINE))


def get_soup(session: Fetcher, url: str, delay: float = 0.0) -> BeautifulSoup:
    if delay:
        time.sleep(delay)
    return BeautifulSoup(session.get_html(url), "lxml")


# --------------------------------------------------------------------------- #
# Text helpers
# --------------------------------------------------------------------------- #
def clean(text: str | None) -> str:
    if not text:
        return ""
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    return text.strip()


def normalise_label(label: str) -> str:
    label = clean(label).rstrip(":").strip()
    return label or "Unnamed"


def excel_safe(value):
    if isinstance(value, str):
        return ILLEGAL_XML_CHARS.sub("", value)
    return value


def safe_sheet_name(name: str, used: set[str]) -> str:
    name = re.sub(r"[\[\]\:\*\?\/\\]", "-", name).strip("' ") or "Sheet"
    name = name[:31]
    base, n = name, 2
    while name.lower() in used:
        suffix = f" ({n})"
        name = base[: 31 - len(suffix)] + suffix
        n += 1
    used.add(name.lower())
    return name


# --------------------------------------------------------------------------- #
# Step 1: discover categories from the "Products" menu
# --------------------------------------------------------------------------- #
def discover_categories(session: requests.Session, delay: float) -> "OrderedDict[str, str]":
    """Return {category name: category url}, in menu order."""
    soup = get_soup(session, BASE_URL, delay)
    host = urlparse(BASE_URL).netloc
    cats: "OrderedDict[str, str]" = OrderedDict()
    seen_urls: set[str] = set()

    for a in soup.select("a[href*='/product-category/']"):
        href = urljoin(BASE_URL, a.get("href", "").strip())
        if urlparse(href).netloc != host:
            continue  # skip external sites (Accuris, Hermle...)
        key = href.rstrip("/").lower()
        if key in seen_urls:
            continue
        name = clean(a.get_text(" "))
        # Skip empty / image-only anchors and the home-page tile links
        # that start with a stray '" ?>' string.
        name = re.sub(r'^["\s?>]+', "", name).strip()
        if not name:
            name = urlparse(href).path.rstrip("/").split("/")[-1].replace("-", " ").title()
        seen_urls.add(key)
        if name in cats:  # same name, different URL
            name = f"{name} ({urlparse(href).path.rstrip('/').split('/')[-1]})"
        cats[name] = href

    return cats


# --------------------------------------------------------------------------- #
# Step 2: list product URLs in a category (handles pagination)
# --------------------------------------------------------------------------- #
def list_product_urls(session: requests.Session, category_url: str, delay: float) -> list[str]:
    urls: "OrderedDict[str, None]" = OrderedDict()
    page_url: str | None = category_url
    visited: set[str] = set()

    while page_url and page_url not in visited:
        visited.add(page_url)
        soup = get_soup(session, page_url, delay)

        anchors = soup.select("ul.products li a[href*='/product/']")
        if not anchors:  # fallback for odd themes
            main = soup.select_one("main, #main, #content, .content-area") or soup
            anchors = main.select("a[href*='/product/']")

        for a in anchors:
            href = urljoin(page_url, a.get("href", "").strip())
            if "/product/" in href and "/product-category/" not in href:
                urls.setdefault(href.split("#")[0], None)

        nxt = soup.select_one("a.next.page-numbers, link[rel='next'], a[rel='next']")
        page_url = urljoin(page_url, nxt["href"]) if nxt and nxt.get("href") else None

    return list(urls)


# --------------------------------------------------------------------------- #
# Step 3: parse one product page
# --------------------------------------------------------------------------- #
def find_heading(soup: BeautifulSoup, keyword: str):
    for h in soup.find_all(re.compile(r"^h[1-6]$")):
        if keyword in clean(h.get_text(" ")).lower():
            return h
    return None


def parse_spec_table(table) -> "OrderedDict[str, str]":
    specs: "OrderedDict[str, str]" = OrderedDict()
    for tr in table.find_all("tr"):
        cells = [clean(c.get_text("\n")) for c in tr.find_all(["th", "td"])]
        cells = [c for c in cells if c != ""]
        if len(cells) < 2:
            continue
        label = normalise_label(cells[0])
        value = " | ".join(cells[1:])
        # keep duplicate labels instead of overwriting them
        key, n = label, 2
        while key in specs:
            key = f"{label} ({n})"
            n += 1
        specs[key] = value
    return specs


def extract_specs(soup: BeautifulSoup) -> "OrderedDict[str, str]":
    # 1) Table that follows the "Specifications" heading.
    h = find_heading(soup, "specification")
    if h:
        table = h.find_next("table")
        if table:
            specs = parse_spec_table(table)
            if specs:
                return specs

    # 2) Any table inside the product area that isn't the grouped list,
    #    the variations form or the WooCommerce "additional information" table.
    scope = soup.select_one("div.product, .single-product, main") or soup
    for table in scope.find_all("table"):
        classes = " ".join(table.get("class", []))
        if "grouped" in classes or "variations" in classes:
            continue
        specs = parse_spec_table(table)
        if specs:
            return specs
    return OrderedDict()


def section_after_heading(heading, stop_at_tags=("h1", "h2")):
    """Yield elements after `heading` until the next sibling-level heading/footer."""
    for el in heading.next_elements:
        name = getattr(el, "name", None)
        if name is None:
            continue
        if name in stop_at_tags and el is not heading:
            return
        if name == "footer":
            return
        yield el


def parse_product(session: requests.Session, url: str, delay: float) -> dict:
    soup = get_soup(session, url, delay)
    row: dict[str, str] = {"Product URL": url}

    # --- name / price / sku ------------------------------------------------
    title = soup.select_one("h1.product_title, h1.entry-title, h1")
    row["Product Name"] = clean(title.get_text(" ")) if title else ""

    price = soup.select_one("p.price, span.price")
    row["Price"] = clean(price.get_text(" ")) if price else ""

    sku = soup.select_one("span.sku")
    row["SKU"] = clean(sku.get_text(" ")) if sku else ""
    if not row["SKU"]:
        # Fall back to the URL slug, which on this site equals the SKU.
        row["SKU"] = urlparse(url).path.rstrip("/").split("/")[-1].upper()

    # --- image -------------------------------------------------------------
    img = soup.select_one(".woocommerce-product-gallery__image a[href]")
    if img:
        row["Image URL"] = urljoin(url, img["href"])
    else:
        im = soup.select_one(".woocommerce-product-gallery img, div.product img")
        row["Image URL"] = urljoin(url, im.get("src", "")) if im else ""

    # --- features (bullet list under the price) / short description --------
    short = soup.select_one(
        ".woocommerce-product-details__short-description, .product-short-description"
    )
    features: list[str] = []
    short_text = ""
    if short:
        features = [clean(li.get_text(" ")) for li in short.find_all("li")]
        features = [f for f in features if f]
        paragraphs = [clean(p.get_text(" ")) for p in short.find_all("p")]
        short_text = "\n".join(p for p in paragraphs if p)
        if not features and not short_text:
            short_text = clean(short.get_text("\n"))
    row["Features"] = "\n".join(f"• {f}" for f in features)
    row["Short Description"] = short_text

    # --- specifications ----------------------------------------------------
    specs = extract_specs(soup)

    # --- optional accessories ---------------------------------------------
    acc_heading = find_heading(soup, "accessories")
    accessories: list[str] = []
    if acc_heading:
        ul = acc_heading.find_next(["ul", "ol"])
        if ul:
            for li in ul.find_all("li", recursive=False) or ul.find_all("li"):
                a = li.find("a", href=True)
                if not a:
                    continue
                label = clean(a.get_text(" "))
                label = re.sub(r"^(placeholder)\s+", "", label, flags=re.I)
                if label.lower() in ("add to quote", ""):
                    # the first link may be the "Add to Quote" button; use the slug
                    label = urlparse(a["href"]).path.rstrip("/").split("/")[-1].upper()
                accessories.append(label)
    row["Optional Accessories"] = ", ".join(dict.fromkeys(accessories))

    # --- grouped products (child items) -----------------------------------
    group_items: list[str] = []
    grouped = soup.select_one("table.woocommerce-grouped-product-list")
    if grouped:
        for a in grouped.select("td.woocommerce-grouped-product-list-item__label a"):
            group_items.append(clean(a.get_text(" ")))
        if not group_items:
            for a in grouped.select("a[href*='/product/']"):
                group_items.append(clean(a.get_text(" ")))
    row["Group Items"] = ", ".join(dict.fromkeys(i for i in group_items if i))

    # --- documents + long description -------------------------------------
    docs: list[str] = []
    desc_parts: list[str] = []
    doc_heading = find_heading(soup, "links and documents") or find_heading(soup, "description")
    if doc_heading:
        doc_exts = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".ppt", ".pptx")
        for el in section_after_heading(doc_heading):
            if el.name == "a" and el.get("href"):
                href = urljoin(url, el["href"])
                if href.lower().split("?")[0].endswith(doc_exts):
                    docs.append(f"{clean(el.get_text(' ')) or 'Document'}: {href}")
            elif el.name == "p":
                txt = clean(el.get_text(" "))
                if txt:
                    desc_parts.append(txt)
    row["Documents"] = "\n".join(dict.fromkeys(docs))
    row["Description"] = "\n\n".join(dict.fromkeys(desc_parts))

    # Spec columns are added last so they never clash with fixed names.
    for k, v in specs.items():
        key = k
        while key in row:  # e.g. a spec literally called "Price"
            key = f"{key} (spec)"
        row[key] = v

    row["_spec_keys"] = list(specs.keys())  # internal; used for column ordering
    return row


# --------------------------------------------------------------------------- #
# Step 4: write the Excel workbook
# --------------------------------------------------------------------------- #
def write_workbook(data: "OrderedDict[str, list[dict]]", path: str) -> None:
    wb = Workbook()
    wb.remove(wb.active)
    used_names: set[str] = set()

    header_fill = PatternFill("solid", start_color="1F4E78")
    header_font = Font(bold=True, color="FFFFFF")

    for category, rows in data.items():
        if not rows:
            continue
        ws = wb.create_sheet(safe_sheet_name(category, used_names))

        # Column order: fixed columns, then spec columns in first-seen order.
        spec_cols: "OrderedDict[str, None]" = OrderedDict()
        for r in rows:
            for k in r:
                if k not in FIXED_COLUMNS and k != "_spec_keys":
                    spec_cols.setdefault(k, None)
        columns = FIXED_COLUMNS + list(spec_cols)

        ws.append(columns)
        for r in rows:
            ws.append([excel_safe(r.get(c, "")) for c in columns])

        # formatting
        for cell in ws[1]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(vertical="center", wrap_text=True)
        ws.freeze_panes = "C2"  # keep Category + Product Name visible
        ws.auto_filter.ref = ws.dimensions

        for idx, col in enumerate(columns, start=1):
            longest = max(
                (len(str(c.value).split("\n")[0]) for c in ws[get_column_letter(idx)] if c.value),
                default=10,
            )
            ws.column_dimensions[get_column_letter(idx)].width = min(max(12, longest + 2), 60)
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                cell.alignment = Alignment(vertical="top", wrap_text=True)

    if not wb.sheetnames:
        raise RuntimeError("No products were scraped - nothing to write.")
    wb.save(path)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="Scrape Benchmark Scientific products to Excel")
    ap.add_argument("-o", "--output", default="benchmarkscientific_products.xlsx")
    ap.add_argument("--workers", type=int, default=4, help="parallel product-page downloads")
    ap.add_argument("--delay", type=float, default=0.3, help="seconds to sleep before each request")
    ap.add_argument(
        "--only",
        action="append",
        default=[],
        help="only scrape categories whose URL slug / name contains this text (repeatable)",
    )
    ap.add_argument("--engine", choices=["auto", "curl_cffi", "requests", "playwright"], default="auto")
    ap.add_argument("--headed", action="store_true", help="show the browser window (playwright engine)")
    args = ap.parse_args()

    global ENGINE, HEADED
    ENGINE, HEADED = args.engine, args.headed
    if resolve_engine(ENGINE) == "playwright":
        args.workers = 1  # a single shared browser page
    print(f"HTTP engine: {resolve_engine(ENGINE)}")
    session = make_session()

    print("Discovering categories ...")
    try:
        categories = discover_categories(session, args.delay)
    except Exception as e:
        print(f"\nCould not load the site: {e}", file=sys.stderr)
        print("The site's firewall is blocking this client. Try, in order:\n"
              "  1) pip install curl_cffi   (then rerun)\n"
              "  2) pip install playwright && playwright install chromium\n"
              "     python scrape_benchmarkscientific.py --engine playwright --headed", file=sys.stderr)
        return 1
    if args.only:
        wanted = [w.lower() for w in args.only]
        categories = OrderedDict(
            (n, u) for n, u in categories.items() if any(w in n.lower() or w in u.lower() for w in wanted)
        )
    if not categories:
        print("No categories found.", file=sys.stderr)
        return 1
    for n, u in categories.items():
        print(f"  - {n}: {u}")

    # category -> list of product URLs
    cat_products: "OrderedDict[str, list[str]]" = OrderedDict()
    for name, url in categories.items():
        try:
            cat_products[name] = list_product_urls(session, url, args.delay)
        except Exception as e:
            print(f"  ! could not list {name}: {e}", file=sys.stderr)
            cat_products[name] = []
        print(f"{name}: {len(cat_products[name])} products")

    # Download every unique product page once (products may be in several categories).
    unique_urls = list(OrderedDict.fromkeys(u for urls in cat_products.values() for u in urls))
    print(f"\nFetching {len(unique_urls)} unique product pages ...")
    parsed: dict[str, dict] = {}

    def work(u: str):
        # each thread gets its own session (requests.Session is not guaranteed thread-safe)
        return u, parse_product(make_session(), u, args.delay)

    failures: list[str] = []
    total = len(unique_urls)

    if args.workers <= 1:
        # Sequential, in the MAIN thread. Required for Playwright (its sync API
        # cannot be used from a different thread than the one that started it).
        for i, u in enumerate(unique_urls, start=1):
            try:
                parsed[u] = parse_product(session, u, args.delay)
            except Exception as e:
                failures.append(u)
                print(f"  ! failed {u}: {e}", file=sys.stderr)
            if i % 10 == 0 or i == total:
                print(f"  {i}/{total}")
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(work, u): u for u in unique_urls}
            for i, fut in enumerate(as_completed(futures), start=1):
                u = futures[fut]
                try:
                    parsed[u] = fut.result()[1]
                except Exception as e:  # keep going if a single page fails
                    failures.append(u)
                    print(f"  ! failed {u}: {e}", file=sys.stderr)
                if i % 20 == 0 or i == total:
                    print(f"  {i}/{total}")

    if failures:
        print(f"\n{len(failures)} page(s) failed; they will be missing from the workbook.", file=sys.stderr)

    # Close the shared browser cleanly if Playwright was used.
    if _PW_STATE:
        try:
            _PW_STATE["browser"].close()
            _PW_STATE["pw"].stop()
        except Exception:
            pass

    # Build per-category row lists (preserving the menu order).
    data: "OrderedDict[str, list[dict]]" = OrderedDict()
    for cat, urls in cat_products.items():
        rows = []
        for u in urls:
            if u in parsed:
                r = dict(parsed[u])
                r["Category"] = cat
                rows.append(r)
        data[cat] = rows

    write_workbook(data, args.output)
    total = sum(len(v) for v in data.values())
    print(f"\nDone. {total} rows across {sum(1 for v in data.values() if v)} sheets -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())