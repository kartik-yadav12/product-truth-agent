import os
import re
import requests

from bs4 import BeautifulSoup
from urllib.parse import quote_plus
from rapidfuzz.fuzz import ratio


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Product Truth Agent; research bot)"
}


def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def is_search_engine_url(url):
    """Return True for search-engine redirect/tracking URLs."""
    if not url:
        return True

    url = url.lower()

    bad_patterns = [
        "bing.com/ck/",
        "bing.com/aclick",
        "google.com/url",
        "googleadservices.com",
        "search.yahoo.com",
        "yandex.ru/clck",
    ]

    return any(pattern in url for pattern in bad_patterns)


def extract_page(url, max_chars=18000):
    try:
        r = requests.get(
            url,
            headers=HEADERS,
            timeout=15,
            allow_redirects=True,
        )

        r.raise_for_status()

        soup = BeautifulSoup(r.text, "html.parser")

        for x in soup(["script", "style", "noscript"]):
            x.decompose()

        title = clean(
            soup.title.get_text(" ", strip=True)
            if soup.title
            else ""
        )

        text = clean(
            soup.get_text(" ", strip=True)
        )

        # IMPORTANT:
        # r.url is the final URL after redirects.
        final_url = r.url

        return {
            "url": final_url,
            "title": title,
            "text": text[:max_chars],
            "status": r.status_code,
        }

    except Exception as e:
        return {
            "url": url,
            "title": "",
            "text": "",
            "status": None,
            "error": str(e),
        }


def search_web(query, limit=6):
    """
    Search Bing and return search results.

    Note:
    Bing may return tracking/redirect URLs.
    Those are resolved later by extract_page().
    """

    url = "https://www.bing.com/search?q=" + quote_plus(query)

    try:
        r = requests.get(
            url,
            headers=HEADERS,
            timeout=15,
        )

        r.raise_for_status()

        soup = BeautifulSoup(r.text, "html.parser")
        results = []

        for li in soup.select("li.b_algo")[:limit]:

            a = li.select_one("h2 a")
            p = li.select_one(".b_caption p")

            if not a or not a.get("href"):
                continue

            results.append({
                "title": clean(
                    a.get_text(" ", strip=True)
                ),
                "url": a["href"],
                "snippet": clean(
                    p.get_text(" ", strip=True)
                    if p
                    else ""
                ),
            })

        return results

    except Exception:
        return []


def product_queries(row):
    barcode = clean(row.get("EXTERNAL_CODE"))
    brand = clean(row.get("BRAND"))
    desc = clean(row.get("RETAILER_DESC"))

    qs = []

    # Barcode is the strongest identifier.
    if barcode:
        qs.append(f'"{barcode}"')

    if barcode and brand:
        qs.append(f'"{barcode}" "{brand}"')

    if brand and desc:
        qs.append(
            f'"{brand}" {desc[:140]}'
        )

    # If there is no barcode, search using the
    # strongest available product description.
    if not barcode and desc:
        if brand:
            qs.append(f'"{brand}" {desc[:140]}')
        else:
            qs.append(f'"{desc[:160]}"')

    return qs


def retrieve_product(row, max_results=6):

    candidates = []
    seen_urls = set()

    # --------------------------------------------------
    # 1. SEARCH
    # --------------------------------------------------

    for q in product_queries(row):

        for x in search_web(q, max_results):

            url = x.get("url")

            if not url:
                continue

            if url in seen_urls:
                continue

            seen_urls.add(url)
            candidates.append(x)

        if len(candidates) >= max_results:
            break

    # --------------------------------------------------
    # 2. SCORE + FETCH ACTUAL PAGE
    # --------------------------------------------------

    scored = []

    barcode = clean(
        row.get("EXTERNAL_CODE")
    ).lower()

    brand = clean(
        row.get("BRAND")
    ).lower()

    description = clean(
        row.get("RETAILER_DESC")
    ).lower()

    target = (
        f"{brand} {description} {barcode}"
    ).strip()

    for c in candidates:

        search_text = (
            c.get("title", "")
            + " "
            + c.get("snippet", "")
        ).lower()

        score = ratio(
            target,
            search_text
        ) / 100

        # --------------------------------------------------
        # Barcode match
        # --------------------------------------------------

        if barcode and barcode in search_text:
            score += 0.35

        # --------------------------------------------------
        # Brand match
        # --------------------------------------------------

        if brand and brand in search_text:
            score += 0.08

        # --------------------------------------------------
        # Fetch page
        # --------------------------------------------------

        page = extract_page(
            c["url"]
        )

        page_url = page.get("url") or c["url"]

        page_text = (
            page.get("text", "")
            .lower()
        )

        page_title = (
            page.get("title", "")
            .lower()
        )

        # --------------------------------------------------
        # Barcode on actual page
        # --------------------------------------------------

        if barcode and barcode in page_text:
            score += 0.45

        # --------------------------------------------------
        # Brand on actual page
        # --------------------------------------------------

        if brand and brand in page_text:
            score += 0.05

        # --------------------------------------------------
        # Reject unresolved search-engine URLs
        # --------------------------------------------------

        if is_search_engine_url(page_url):
            continue

        # --------------------------------------------------
        # Use FINAL URL, NOT Bing's original URL
        # --------------------------------------------------

        scored.append({
            "title": page.get("title") or c.get("title"),
            "url": page_url,
            "snippet": c.get("snippet", ""),
            "score": round(
                min(score, 1),
                4
            ),
            "page": page,
        })

    return sorted(
        scored,
        key=lambda x: x["score"],
        reverse=True,
    )