#!/usr/bin/env python3
"""
Scrape all products from <URL> into ONE CSV file.

One row per product with:
    Product Name, Short Description, Product Image, SKU,
    Accessories, Specifications (table kept as-is), Description

Everything is controlled from config.yaml.

Install:
    pip install requests beautifulsoup4 lxml pyyaml curl_cffi
    pip install playwright && playwright install chromium     # only for engine: playwright

Run:
    python scrape_benchmarkscientific.py
    python scrape_benchmarkscientific.py --config my_config.yaml
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import threading
import time
from collections import OrderedDict, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
import yaml
from bs4 import BeautifulSoup

ILLEGAL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


# =========================================================================== #
# Config helpers
# =========================================================================== #
def load_config(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        sys.exit(f"Config file not found: {p.resolve()}")
    with open(p, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    return cfg


def cget(cfg: dict, dotted: str, default=None):
    """cget(cfg, 'http.engine', 'auto')"""
    cur = cfg
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return default if cur is None else cur


# =========================================================================== #
# HTTP layer  (curl_cffi / requests / playwright)
# =========================================================================== #
class HttpError(RuntimeError):
    pass


def resolve_engine(engine: str) -> str:
    if engine != "auto":
        return engine
    try:
        import curl_cffi  # noqa: F401
        return "curl_cffi"
    except ImportError:
        return "requests"


class Fetcher:
    # Playwright's sync API is bound to the thread that started it, so the
    # browser is shared and only ever used from the main thread (workers = 1).
    _pw: dict = {}

    def __init__(self, cfg: dict):
        self.engine = resolve_engine(cget(cfg, "http.engine", "auto"))
        self.headed = bool(cget(cfg, "http.headed", False))
        self.timeout = cget(cfg, "http.timeout", 30)
        self.retries = int(cget(cfg, "http.retries", 4))
        self.ua = cget(cfg, "http.user_agent", "Mozilla/5.0")
        self.session = None
        if self.engine == "curl_cffi":
            from curl_cffi import requests as cr
            self.session = cr.Session(impersonate="chrome")
        elif self.engine == "requests":
            self.session = requests.Session()
            self.session.headers.update({"User-Agent": self.ua, "Accept-Language": "en-US,en;q=0.9"})

    def _playwright_get(self, url: str) -> str:
        if "page" not in Fetcher._pw:
            from playwright.sync_api import sync_playwright
            pw = sync_playwright().start()
            browser = pw.chromium.launch(headless=not self.headed)
            ctx = browser.new_context(user_agent=self.ua, locale="en-US")
            Fetcher._pw.update(pw=pw, browser=browser, page=ctx.new_page())
        page = Fetcher._pw["page"]
        resp = page.goto(url, wait_until="domcontentloaded", timeout=int(self.timeout * 2000))
        page.wait_for_timeout(1500)
        if resp is not None and resp.status >= 400:
            raise HttpError(f"HTTP {resp.status} for {url}")
        return page.content()

    def get_html(self, url: str) -> str:
        if self.engine == "playwright":
            return self._playwright_get(url)
        last = None
        for attempt in range(self.retries):
            try:
                r = self.session.get(url, timeout=self.timeout)
                if r.status_code == 200:
                    return r.text
                last = f"HTTP {r.status_code}"
            except Exception as e:  # network hiccup
                last = str(e)
            time.sleep(1.5 * (attempt + 1))
        raise HttpError(f"{last} for {url}")

    @staticmethod
    def close():
        if Fetcher._pw:
            try:
                Fetcher._pw["browser"].close()
                Fetcher._pw["pw"].stop()
            except Exception:
                pass
            Fetcher._pw.clear()


_local = threading.local()


def thread_fetcher(cfg: dict) -> Fetcher:
    """One Fetcher per worker thread."""
    if not hasattr(_local, "f"):
        _local.f = Fetcher(cfg)
    return _local.f


def get_soup(fetcher: Fetcher, url: str, cfg: dict) -> BeautifulSoup:
    delay = float(cget(cfg, "http.delay", 0))
    if delay:
        time.sleep(delay)
    return BeautifulSoup(fetcher.get_html(url), "lxml")


# =========================================================================== #
# Small parsing helpers
# =========================================================================== #
def clean(text) -> str:
    if not text:
        return ""
    text = str(text).replace("\xa0", " ")
    text = ILLEGAL_CHARS.sub("", text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    return text.strip()


def sel_one(root, selectors):
    """First element matched by a CSS selector (or list of selectors)."""
    if not selectors:
        return None
    if isinstance(selectors, str):
        selectors = [selectors]
    for s in selectors:
        try:
            el = root.select_one(s)
        except Exception:
            el = None
        if el is not None:
            return el
    return None


def find_heading(soup, keyword: str):
    keyword = keyword.lower()
    for h in soup.find_all(re.compile(r"^h[1-6]$")):
        if keyword in clean(h.get_text(" ")).lower():
            return h
    return None


def slug_of(url: str) -> str:
    return urlparse(url).path.rstrip("/").split("/")[-1]


def img_url(img, base: str) -> str:
    """Real image URL, skipping lazy-load placeholders."""
    if img is None:
        return ""
    for attr in ("data-lazy-src", "data-src", "data-large_image", "src"):
        v = (img.get(attr) or "").strip()
        if v and not v.startswith("data:"):
            return urljoin(base, v)
    srcset = (img.get("data-srcset") or img.get("srcset") or "").strip()
    if srcset:
        return urljoin(base, srcset.split(",")[0].split()[0])
    return ""


class SafeDict(defaultdict):
    def __init__(self, d):
        super().__init__(str, d)


# =========================================================================== #
# Step 1: categories -> product URLs
# =========================================================================== #
def discover_categories(fetcher: Fetcher, cfg: dict) -> "OrderedDict[str, str]":
    base = cget(cfg, "site.base_url")
    pat = cget(cfg, "discovery.category_url_pattern", "/product-category/")
    include = [w.lower() for w in cget(cfg, "discovery.include", [])]
    exclude = [w.lower() for w in cget(cfg, "discovery.exclude", [])]
    host = urlparse(base).netloc

    soup = get_soup(fetcher, base, cfg)
    cats: "OrderedDict[str, str]" = OrderedDict()
    seen: set[str] = set()

    for a in soup.select(f"a[href*='{pat}']"):
        href = urljoin(base, a.get("href", "").strip())
        if urlparse(href).netloc != host:
            continue
        key = href.rstrip("/").lower()
        if key in seen:
            continue
        name = re.sub(r'^["\s?>]+', "", clean(a.get_text(" "))).strip()
        if not name:
            name = slug_of(href).replace("-", " ").title()
        hay = f"{name} {href}".lower()
        if include and not any(w in hay for w in include):
            continue
        if any(w in hay for w in exclude):
            continue
        seen.add(key)
        if name in cats:
            name = f"{name} ({slug_of(href)})"
        cats[name] = href

    for extra in cget(cfg, "discovery.extra_category_urls", []):
        extra = urljoin(base, extra)
        if extra.rstrip("/").lower() not in seen:
            cats[slug_of(extra) or extra] = extra
    return cats


def list_product_urls(fetcher: Fetcher, category_url: str, cfg: dict) -> list[str]:
    ppat = cget(cfg, "discovery.product_url_pattern", "/product/")
    cpat = cget(cfg, "discovery.category_url_pattern", "/product-category/")
    link_sel = cget(cfg, "selectors.product_links", ["ul.products li a[href*='/product/']"])
    next_sel = cget(cfg, "selectors.next_page", "a.next.page-numbers")
    if isinstance(link_sel, str):
        link_sel = [link_sel]

    urls: "OrderedDict[str, None]" = OrderedDict()
    page_url, visited = category_url, set()
    while page_url and page_url not in visited:
        visited.add(page_url)
        soup = get_soup(fetcher, page_url, cfg)
        anchors = []
        for s in link_sel:
            anchors = soup.select(s)
            if anchors:
                break
        if not anchors:  # fallback for odd themes
            main = soup.select_one("main, #main, #content, .content-area") or soup
            anchors = main.select(f"a[href*='{ppat}']")
        for a in anchors:
            href = urljoin(page_url, a.get("href", "").strip()).split("#")[0]
            if ppat in href and cpat not in href:
                urls.setdefault(href, None)
        nxt = soup.select_one(next_sel) if next_sel else None
        page_url = urljoin(page_url, nxt["href"]) if nxt is not None and nxt.get("href") else None
    return list(urls)


# =========================================================================== #
# Step 2: parse one product page
# =========================================================================== #
def parse_basic(soup: BeautifulSoup, url: str, cfg: dict) -> dict:
    """Name, short description, image, SKU (+ price) of any product page."""
    out: dict = {"url": url}

    h1 = sel_one(soup, cget(cfg, "selectors.product_name", "h1"))
    out["name"] = clean(h1.get_text(" ")) if h1 else ""

    # --- short description (bullet list under the title) ----------------------
    items: list[str] = []
    node = sel_one(soup, cget(cfg, "selectors.short_description"))
    if node is not None:
        items = [clean(li.get_text(" ")) for li in node.find_all("li")]
        if not any(items):
            items = [clean(p.get_text(" ")) for p in node.find_all("p")] or [clean(node.get_text("\n"))]
    if not any(items) and h1 is not None:
        ul = h1.find_next("ul")
        if ul is not None and not ul.find_parent(["nav", "header", "footer"]):
            items = [clean(li.get_text(" ")) for li in ul.find_all("li")]
    items = [i for i in items if i]
    prefix = cget(cfg, "short_description.bullet_prefix", "")
    out["short_items"] = items
    out["short_description"] = "\n".join(f"{prefix}{i}" for i in items)

    # --- SKU --------------------------------------------------------------------
    sku_el = sel_one(soup, cget(cfg, "selectors.sku", "span.sku"))
    sku = clean(sku_el.get_text(" ")) if sku_el else ""
    if not sku:
        m = re.search(r"SKU:\s*([A-Za-z0-9\-_./]+)", soup.get_text(" "))
        sku = m.group(1) if m else slug_of(url).upper()
    out["sku"] = re.sub(r"^SKU:\s*", "", sku, flags=re.I)

    # --- main image -------------------------------------------------------------
    image = ""
    for s in (cget(cfg, "selectors.image", []) or []):
        el = soup.select_one(s)
        if el is None:
            continue
        if el.name == "meta":
            image = urljoin(url, el.get("content", ""))
        elif el.name == "a":
            image = urljoin(url, el.get("href", ""))
        else:
            image = img_url(el, url)
        if image:
            break
    out["image"] = image

    price = soup.select_one("p.price, span.price")
    out["price"] = clean(price.get_text(" ")) if price else ""
    return out


def parse_spec_table(table) -> list[tuple[str, str]]:
    """Rows of the table, exactly as written (label, value); empty cells dropped."""
    rows: list[tuple[str, str]] = []
    for tr in table.find_all("tr"):
        cells = [clean(c.get_text("\n")) for c in tr.find_all(["th", "td"])]
        cells = [c for c in cells if c]
        if len(cells) >= 2:
            rows.append((cells[0], " | ".join(cells[1:])))
        elif len(cells) == 1 and tr.find("th"):
            rows.append((cells[0], ""))  # section header row inside the table
    return rows


def find_spec_table(soup: BeautifulSoup, cfg: dict):
    custom = cget(cfg, "selectors.specs_table")
    if custom:
        t = sel_one(soup, custom)
        if t is not None:
            return t
    h = find_heading(soup, "specification")
    if h is not None:
        t = h.find_next("table")
        if t is not None:
            return t
    for t in soup.find_all("table"):
        classes = " ".join(t.get("class", []))
        if "grouped" in classes or "variations" in classes:
            continue
        if parse_spec_table(t):
            return t
    return None


def extract_description(soup: BeautifulSoup, table, cfg: dict) -> str:
    min_len = int(cget(cfg, "description.min_length", 40))

    def text_of(node) -> str:
        paras = [clean(p.get_text(" ")) for p in node.find_all("p")]
        paras = [p for p in paras if p]
        return "\n\n".join(paras) if paras else clean(node.get_text("\n"))

    # 1) explicit selector from config, 2) standard WooCommerce description tab
    for s in (cget(cfg, "selectors.description"), "#tab-description, .woocommerce-Tabs-panel--description"):
        node = sel_one(soup, s) if s else None
        if node is not None and text_of(node):
            return text_of(node)

    # 3) auto: climb from the specifications table to the nearest block that also
    #    holds a long text paragraph (the description sits beside the table).
    if table is None:
        return ""

    def usable(el) -> bool:
        if el.find_parent(["table", "ul", "ol", "footer", "header", "nav"]):
            return False
        if el.find_parent(class_=re.compile(r"products|related|upsells")):
            return False
        return True

    anc = table
    for _ in range(8):
        anc = anc.parent
        if anc is None or anc.name in ("body", "html"):
            break
        blocks = anc.select(".elementor-widget-text-editor") or anc.find_all("p")
        texts = []
        for b in blocks:
            if not usable(b):
                continue
            t = text_of(b)
            if len(t) >= min_len:
                texts.append(t)
        if texts:
            return "\n\n".join(dict.fromkeys(texts))
    return ""


def extract_accessories(soup: BeautifulSoup, url: str, cfg: dict) -> list[dict]:
    keyword = cget(cfg, "accessories.heading_keyword", "accessor")
    item_sel = cget(cfg, "accessories.item_selector", "li.product")
    title_sel = cget(cfg, "accessories.title_selector", "h2, h3")
    ppat = cget(cfg, "discovery.product_url_pattern", "/product/")
    self_url = url.rstrip("/").lower()

    heading = find_heading(soup, keyword)
    if heading is None:
        return []

    def is_quote_btn(a) -> bool:
        txt = clean(a.get_text(" ")).lower()
        classes = " ".join(a.get("class", []))
        return "add to quote" in txt or "add_to_cart" in classes or "add-to-quote" in classes

    cards, node = [], heading
    for _ in range(6):  # climb until the section that holds the cards
        node = node.parent
        if node is None:
            break
        cards = node.select(item_sel)
        if cards:
            break

    results: list[dict] = []
    if cards:
        for card in cards:
            link = ""
            for a in card.select(f"a[href*='{ppat}']"):
                if not is_quote_btn(a):
                    link = urljoin(url, a["href"]).split("#")[0]
                    break
            title = sel_one(card, title_sel)
            name = clean(title.get_text(" ")) if title else ""
            if not name:
                for a in card.find_all("a"):
                    if not is_quote_btn(a) and clean(a.get_text(" ")):
                        name = clean(a.get_text(" "))
                        break
            name = re.sub(r"^placeholder\s+", "", name, flags=re.I)
            if not name and link:
                name = slug_of(link).upper()
            results.append({"name": name, "image": img_url(card.find("img"), url), "url": link})
    else:
        # Fallback: group product links inside the section by URL.
        node = heading
        for _ in range(5):
            node = node.parent
            if node is None:
                break
            anchors = [a for a in node.select(f"a[href*='{ppat}']") if not is_quote_btn(a)]
            if anchors:
                grouped: "OrderedDict[str, dict]" = OrderedDict()
                for a in anchors:
                    href = urljoin(url, a["href"]).split("#")[0]
                    g = grouped.setdefault(href, {"name": "", "image": "", "url": href})
                    g["name"] = g["name"] or clean(a.get_text(" "))
                    g["image"] = g["image"] or img_url(a.find("img"), url)
                for g in grouped.values():
                    g["name"] = g["name"] or slug_of(g["url"]).upper()
                results = list(grouped.values())
                break

    # drop the product itself and duplicates
    seen, final = set(), []
    for r in results:
        if r["url"] and r["url"].rstrip("/").lower() == self_url:
            continue
        key = (r["name"], r["url"])
        if key in seen or not (r["name"] or r["url"]):
            continue
        seen.add(key)
        final.append(r)
    return final


_basic_cache: dict[str, dict] = {}
_cache_lock = threading.Lock()


def accessory_details(fetcher: Fetcher, url: str, cfg: dict) -> dict:
    with _cache_lock:
        if url in _basic_cache:
            return _basic_cache[url]
    try:
        info = parse_basic(get_soup(fetcher, url, cfg), url, cfg)
    except Exception as e:
        print(f"  ! accessory page failed {url}: {e}", file=sys.stderr)
        info = {}
    with _cache_lock:
        _basic_cache[url] = info
    return info


def parse_product(fetcher: Fetcher, url: str, cfg: dict) -> dict:
    soup = get_soup(fetcher, url, cfg)
    basic = parse_basic(soup, url, cfg)

    table = find_spec_table(soup, cfg)
    specs = parse_spec_table(table) if table is not None else []
    description = extract_description(soup, table, cfg)

    accessories = extract_accessories(soup, url, cfg)
    if cget(cfg, "accessories.fetch_details", False):
        for acc in accessories:
            if acc["url"]:
                d = accessory_details(fetcher, acc["url"], cfg)
                acc["sku"] = d.get("sku", "")
                acc["price"] = d.get("price", "")
                acc["short_description"] = "; ".join(d.get("short_items", []))
                acc["name"] = acc["name"] or d.get("name", "")
                acc["image"] = acc["image"] or d.get("image", "")

    tpl = cget(cfg, "accessories.template", "{name} | {image} | {url}")
    sep = cget(cfg, "accessories.separator", "\n")
    acc_text = sep.join(tpl.format_map(SafeDict(a)) for a in accessories)

    return {
        "product_name": basic["name"],
        "short_description": basic["short_description"],
        "product_image": basic["image"],
        "sku": basic["sku"],
        "accessories": acc_text,
        "description": description,
        "product_url": url,
        "_specs": specs,
    }


# =========================================================================== #
# Step 3: write the single CSV
# =========================================================================== #
def write_csv(rows: list[dict], cfg: dict) -> str:
    out_file = cget(cfg, "output.file", "benchmarkscientific_products.csv")
    encoding = cget(cfg, "output.encoding", "utf-8-sig")
    columns = cget(cfg, "output.columns", [])
    mode = cget(cfg, "specifications.mode", "cell")
    row_tpl = cget(cfg, "specifications.row_template", "{label} | {value}")
    row_sep = cget(cfg, "specifications.row_separator", "\n")

    # Spec labels (first-seen order) for 'columns' mode; repeated labels inside one
    # product are numbered so nothing is overwritten.
    per_product_specs: list["OrderedDict[str, str]"] = []
    spec_headers: "OrderedDict[str, None]" = OrderedDict()
    for r in rows:
        d: "OrderedDict[str, str]" = OrderedDict()
        for label, value in r["_specs"]:
            key, n = label, 2
            while key in d:
                key = f"{label} ({n})"
                n += 1
            d[key] = value
            spec_headers.setdefault(key, None)
        per_product_specs.append(d)

    # Build the header and a getter per output column.
    headers: list[str] = []
    getters = []
    fixed_headers = {c.get("header", c["field"]) for c in columns if c.get("field") != "specifications"}
    for col in columns:
        field, header = col["field"], col.get("header", col["field"])
        if field == "specifications" and mode == "columns":
            for label in spec_headers:
                h = f"{label} (spec)" if label in fixed_headers else label
                headers.append(h)
                getters.append(lambda r, i, label=label: per_product_specs[i].get(label, ""))
        elif field == "specifications":
            headers.append(header)
            getters.append(
                lambda r, i: row_sep.join(row_tpl.format(label=l, value=v) for l, v in r["_specs"])
            )
        else:
            headers.append(header)
            getters.append(lambda r, i, field=field: r.get(field, ""))

    Path(out_file).parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", newline="", encoding=encoding) as f:
        w = csv.writer(f)
        w.writerow(headers)
        for i, r in enumerate(rows):
            w.writerow([clean_cell(g(r, i)) for g in getters])
    return out_file


def clean_cell(v) -> str:
    return ILLEGAL_CHARS.sub("", v) if isinstance(v, str) else ("" if v is None else str(v))


# =========================================================================== #
# Main
# =========================================================================== #
def main() -> int:
    ap = argparse.ArgumentParser(description="Scrape Benchmark Scientific products to CSV")
    ap.add_argument("-c", "--config", default=str(Path(__file__).with_name("config.yaml")),
                    help="path to the YAML config (default: config.yaml next to this script)")
    args = ap.parse_args()
    cfg = load_config(args.config)

    engine = resolve_engine(cget(cfg, "http.engine", "auto"))
    workers = 1 if engine == "playwright" else max(1, int(cget(cfg, "http.workers", 4)))
    print(f"HTTP engine: {engine} | workers: {workers}")

    fetcher = Fetcher(cfg)
    try:
        print("Discovering categories ...")
        try:
            categories = discover_categories(fetcher, cfg)
        except Exception as e:
            print(f"\nCould not load the site: {e}", file=sys.stderr)
            print("If this is a 403, set http.engine to 'curl_cffi' or 'playwright' in the config.",
                  file=sys.stderr)
            return 1
        if not categories:
            print("No categories found (check discovery.include / exclude).", file=sys.stderr)
            return 1

        product_urls: "OrderedDict[str, None]" = OrderedDict()
        for name, url in categories.items():
            try:
                urls = list_product_urls(fetcher, url, cfg)
            except Exception as e:
                print(f"  ! could not list {name}: {e}", file=sys.stderr)
                continue
            print(f"  {name}: {len(urls)} products")
            for u in urls:
                product_urls.setdefault(u, None)

        urls = list(product_urls)
        total = len(urls)
        print(f"\nFetching {total} unique product pages ...")
        parsed: dict[str, dict] = {}
        failures: list[str] = []

        if workers == 1:  # main thread (required for playwright)
            for i, u in enumerate(urls, 1):
                try:
                    parsed[u] = parse_product(fetcher, u, cfg)
                except Exception as e:
                    failures.append(u)
                    print(f"  ! failed {u}: {e}", file=sys.stderr)
                if i % 10 == 0 or i == total:
                    print(f"  {i}/{total}")
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futs = {pool.submit(lambda u: parse_product(thread_fetcher(cfg), u, cfg), u): u for u in urls}
                for i, fut in enumerate(as_completed(futs), 1):
                    u = futs[fut]
                    try:
                        parsed[u] = fut.result()
                    except Exception as e:
                        failures.append(u)
                        print(f"  ! failed {u}: {e}", file=sys.stderr)
                    if i % 20 == 0 or i == total:
                        print(f"  {i}/{total}")
    finally:
        Fetcher.close()

    rows = [parsed[u] for u in urls if u in parsed]  # keep site order
    if not rows:
        print("No products were scraped - nothing to write.", file=sys.stderr)
        return 1
    path = write_csv(rows, cfg)
    print(f"\nDone. {len(rows)} products -> {path}")
    if failures:
        print(f"{len(failures)} page(s) failed and are missing from the CSV.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())