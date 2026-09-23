"""Web retrieval: find candidate product pages and score them against the item."""

from __future__ import annotations

import base64
import logging
import os
import re
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import requests
from bs4 import BeautifulSoup
from rapidfuzz.fuzz import ratio

from .barcode import as_evidence, lookup_barcode


log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}

MAX_SEARCH_RESULTS = int(os.getenv("MAX_SEARCH_RESULTS", "6"))
MAX_PAGE_CHARS = int(os.getenv("MAX_PAGE_CHARS", "18000"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "15"))
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "").strip()

# Scraped results are frequently irrelevant (the engines degrade automated
# traffic rather than refusing it), so anything that does not look like this
# product is dropped instead of being fed to the model as "evidence".
MIN_EVIDENCE_SCORE = float(os.getenv("MIN_EVIDENCE_SCORE", "0.35"))

# Search-engine redirect/tracking URLs; never usable as evidence.
BLOCKED_URL_PATTERNS = (
    "bing.com/ck/",
    "bing.com/aclick",
    "google.com/url",
    "googleadservices.com",
    "search.yahoo.com",
    "yandex.ru/clck",
    "duckduckgo.com/y.js",
)

_SESSION = requests.Session()
_SESSION.headers.update(HEADERS)
_SESSION.verify = os.getenv("PTA_INSECURE_SSL", "").strip().lower() not in {
    "1",
    "true",
    "yes",
}


def _log_request_failure(source, exc):
    """Search failures used to be swallowed silently, which hid TLS problems."""
    if isinstance(exc, requests.exceptions.SSLError):
        log.error(
            "%s: TLS verification failed. On a network that intercepts TLS, "
            "install `truststore` (in requirements.txt) or set REQUESTS_CA_BUNDLE "
            "to your corporate CA bundle. Details: %s",
            source,
            exc,
        )
    else:
        log.warning("%s request failed: %s", source, exc)


def clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def is_search_engine_url(url) -> bool:
    if not url:
        return True
    lowered = url.lower()
    if not lowered.startswith(("http://", "https://")):
        return True
    return any(pattern in lowered for pattern in BLOCKED_URL_PATTERNS)


def unwrap_redirect(url):
    """Recover the destination URL from a search-engine redirect wrapper.

    Bing serves every organic result as `bing.com/ck/a?...&u=<base64>`. The
    redirect is performed client side, so following it with `requests` just
    returns Bing's own HTML - the target has to be decoded out of the `u`
    parameter instead. DuckDuckGo and Google use plain URL-encoded parameters.
    """
    if not url:
        return url

    try:
        parsed = urlparse(url)
    except ValueError:
        return url

    host = parsed.netloc.lower()
    params = parse_qs(parsed.query)

    if "bing.com" in host and "/ck/a" in parsed.path:
        raw = (params.get("u") or [""])[0]
        if raw:
            # Bing prefixes the base64url payload with "a1".
            payload = raw[2:] if raw.startswith("a1") else raw
            payload += "=" * (-len(payload) % 4)
            try:
                decoded = base64.urlsafe_b64decode(payload).decode("utf8", "replace")
                if decoded.startswith(("http://", "https://")):
                    return decoded
            except (ValueError, base64.binascii.Error):
                pass
        return url

    for host_fragment, param in (
        ("duckduckgo.com", "uddg"),
        ("google.com", "q"),
        ("google.com", "url"),
    ):
        if host_fragment in host and param in params:
            decoded = unquote(params[param][0])
            if decoded.startswith(("http://", "https://")):
                return decoded

    return url


def extract_page(url, max_chars=MAX_PAGE_CHARS):
    try:
        response = _SESSION.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()

        title = clean(soup.title.get_text(" ", strip=True)) if soup.title else ""

        return {
            # response.url is the final URL after redirects.
            "url": response.url,
            "title": title,
            "text": clean(soup.get_text(" ", strip=True))[:max_chars],
            "status": response.status_code,
        }
    except requests.RequestException as exc:
        _log_request_failure(f"fetch {url}", exc)
        return {"url": url, "title": "", "text": "", "status": None, "error": str(exc)}


# ----------------------------------------------------------------------
# search providers
# ----------------------------------------------------------------------


def _search_tavily(query, limit):
    """Licensed provider; preferred when TAVILY_API_KEY is configured."""
    try:
        response = _SESSION.post(
            "https://api.tavily.com/search",
            json={
                "api_key": TAVILY_API_KEY,
                "query": query,
                "max_results": limit,
                "search_depth": "basic",
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return [
            {
                "title": clean(r.get("title")),
                "url": r.get("url"),
                "snippet": clean(r.get("content")),
            }
            for r in response.json().get("results", [])
        ]
    except (requests.RequestException, ValueError) as exc:
        _log_request_failure("tavily", exc)
        return []


def _search_bing(query, limit):
    try:
        response = _SESSION.get(
            "https://www.bing.com/search?q=" + quote_plus(query),
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        results = []
        for li in soup.select("li.b_algo")[:limit]:
            anchor = li.select_one("h2 a")
            caption = li.select_one(".b_caption p")
            if not anchor or not anchor.get("href"):
                continue
            results.append(
                {
                    "title": clean(anchor.get_text(" ", strip=True)),
                    "url": unwrap_redirect(anchor["href"]),
                    "snippet": clean(caption.get_text(" ", strip=True)) if caption else "",
                }
            )
        return results
    except requests.RequestException as exc:
        _log_request_failure("bing", exc)
        return []


def _search_duckduckgo(query, limit):
    """Fallback for when Bing's markup changes or it blocks the request."""
    try:
        response = _SESSION.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        results = []
        for result in soup.select("div.result")[:limit]:
            anchor = result.select_one("a.result__a")
            snippet = result.select_one("a.result__snippet")
            if not anchor or not anchor.get("href"):
                continue
            results.append(
                {
                    "title": clean(anchor.get_text(" ", strip=True)),
                    "url": unwrap_redirect(anchor["href"]),
                    "snippet": clean(snippet.get_text(" ", strip=True)) if snippet else "",
                }
            )
        return results
    except requests.RequestException as exc:
        _log_request_failure("duckduckgo", exc)
        return []


def search_web(query, limit=MAX_SEARCH_RESULTS):
    """Query the configured providers and merge their results, best first.

    Tavily short-circuits when configured because it is the licensed provider.
    Otherwise both scrapers are queried and merged - they surface different
    barcode/retailer sites, and either can be blocked or have its markup
    changed at any time.
    """
    if TAVILY_API_KEY:
        results = _search_tavily(query, limit)
        if results:
            return results

    merged, seen = [], set()
    for provider in (_search_duckduckgo, _search_bing):
        for result in provider(query, limit):
            url = result.get("url")
            if not url or url in seen or is_search_engine_url(url):
                continue
            seen.add(url)
            merged.append(result)

    if not merged:
        log.warning("No usable search results for query %r", query)

    return merged


# ----------------------------------------------------------------------
# query building + scoring
# ----------------------------------------------------------------------


def product_queries(row):
    barcode = clean(row.get("EXTERNAL_CODE"))
    brand = clean(row.get("BRAND"))
    description = clean(row.get("RETAILER_DESC"))

    # "AQUAFRESH (HALEON)" -> "AQUAFRESH"; the parenthetical is the owning group.
    brand_term = clean(re.sub(r"\(.*?\)", " ", brand)) or brand

    queries = []
    if barcode:
        queries.append(f'"{barcode}"')
        if brand_term:
            queries.append(f'"{barcode}" {brand_term}')
    if brand_term and description:
        queries.append(f'"{brand_term}" {description[:140]}')
    elif description:
        queries.append(f'"{description[:160]}"')

    seen = set()
    return [q for q in queries if not (q in seen or seen.add(q))]


def retrieve_product(row, max_results=MAX_SEARCH_RESULTS, max_pages=None):
    """Gather evidence for a product: barcode APIs first, then web search.

    Barcode records come from keyless product APIs keyed on the exact EAN/UPC,
    so they are trusted ahead of anything scraped. Search is best effort - the
    engines actively degrade automated traffic - and any offer URLs surfaced by
    the barcode lookup are fetched as additional pages.
    """
    max_pages = max_results if max_pages is None else max_pages

    barcode_records = lookup_barcode(row.get("EXTERNAL_CODE"))
    barcode_evidence = as_evidence(barcode_records)
    if barcode_evidence:
        log.info(
            "Barcode lookup hit: %s",
            ", ".join(r["source"] for r in barcode_records),
        )

    candidates, seen_urls = [], set()

    # Retailer pages linked from the barcode record are known-good matches.
    for record in barcode_records:
        for url in record.get("offer_urls", []):
            if url not in seen_urls and not is_search_engine_url(url):
                seen_urls.add(url)
                candidates.append(
                    {"title": record["fields"].get("title", ""), "url": url, "snippet": ""}
                )

    for query in product_queries(row):
        for result in search_web(query, max_results):
            url = result.get("url")
            if not url or url in seen_urls or is_search_engine_url(url):
                continue
            seen_urls.add(url)
            candidates.append(result)
        if len(candidates) >= max_results:
            break

    barcode = clean(row.get("EXTERNAL_CODE")).lower()
    brand = clean(row.get("BRAND")).lower()
    description = clean(row.get("RETAILER_DESC")).lower()
    target = f"{brand} {description} {barcode}".strip()

    # Pre-rank on the search snippet so the page fetch budget is spent on the
    # most promising candidates first.
    def snippet_score(candidate):
        text = f"{candidate.get('title', '')} {candidate.get('snippet', '')}".lower()
        score = ratio(target, text) / 100
        if barcode and barcode in text:
            score += 0.35
        if brand and brand in text:
            score += 0.08
        return score

    candidates.sort(key=snippet_score, reverse=True)

    scored = []
    for candidate in candidates[:max_pages]:
        score = snippet_score(candidate)
        page = extract_page(candidate["url"])
        page_url = page.get("url") or candidate["url"]

        # A redirect can still land on a tracking URL.
        if is_search_engine_url(page_url):
            continue

        page_text = page.get("text", "").lower()
        if not page_text.strip():
            continue  # blocked, empty or non-HTML response - no evidence value

        if barcode and barcode in page_text:
            score += 0.45
        if brand and brand in page_text:
            score += 0.05

        if score < MIN_EVIDENCE_SCORE:
            log.debug("Dropping low-relevance page (%.3f): %s", score, page_url)
            continue

        scored.append(
            {
                "title": page.get("title") or candidate.get("title"),
                "url": page_url,
                "domain": urlparse(page_url).netloc,
                "snippet": candidate.get("snippet", ""),
                "score": round(min(score, 1.0), 4),
                "page": page,
            }
        )

    for item in barcode_evidence:
        scored.append(
            {
                "title": item["title"],
                "url": item["url"],
                "domain": item["domain"],
                "snippet": item["snippet"],
                "score": item["score"],
                "page": {"url": item["url"], "title": item["title"], "text": item["page_text"]},
            }
        )

    return sorted(scored, key=lambda x: x["score"], reverse=True)
