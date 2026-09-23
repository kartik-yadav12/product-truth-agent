"""Barcode lookup against public product APIs.

Scraping Bing/DuckDuckGo is unreliable by design: both detect automated
traffic, and Bing responds by serving unrelated results rather than an error
(a barcode query can come back with Microsoft Word support pages). These APIs
are keyless, documented, and keyed on the exact barcode, so when they have the
product the evidence is far stronger than any scraped page.

Responses are cached on disk because the UPCitemdb trial tier allows only
~100 lookups per day.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

import requests


log = logging.getLogger(__name__)

CACHE_DIR = Path(
    os.getenv("PTA_CACHE_DIR", Path(__file__).resolve().parents[1] / ".cache" / "barcode")
)
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "15"))
USER_AGENT = "ProductTruthAgent/1.0 (hackathon research)"

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": USER_AGENT})
_SESSION.verify = os.getenv("PTA_INSECURE_SSL", "").strip().lower() not in {
    "1",
    "true",
    "yes",
}


def _cache_path(barcode):
    return CACHE_DIR / f"{barcode}.json"


def _read_cache(barcode):
    path = _cache_path(barcode)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_cache(barcode, payload):
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(barcode).write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf8"
        )
    except OSError as exc:
        log.debug("Could not cache barcode %s: %s", barcode, exc)


def _get_json(url):
    try:
        response = _SESSION.get(url, timeout=REQUEST_TIMEOUT)
        if response.status_code == 429:
            log.warning("Rate limited by %s", url)
            return None
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        log.warning("Barcode lookup failed for %s: %s", url, exc)
        return None


def _from_upcitemdb(barcode):
    payload = _get_json(f"https://api.upcitemdb.com/prod/trial/lookup?upc={barcode}")
    if not payload:
        return None

    items = payload.get("items") or []
    if not items:
        return None

    item = items[0]
    fields = {
        "title": item.get("title"),
        "brand": item.get("brand"),
        "category": item.get("category"),
        "description": item.get("description"),
        "size": item.get("size"),
        "colour": item.get("color"),
        "model": item.get("model"),
    }
    offers = [o.get("link") for o in (item.get("offers") or []) if o.get("link")]

    return {
        "source": "upcitemdb",
        "url": f"https://www.upcitemdb.com/upc/{barcode}",
        "fields": {k: v for k, v in fields.items() if v},
        "offer_urls": offers[:3],
    }


def _from_open_facts(barcode, host, source):
    payload = _get_json(f"https://{host}/api/v2/product/{barcode}.json")
    if not payload or payload.get("status") != 1:
        return None

    product = payload.get("product") or {}
    fields = {
        "title": product.get("product_name"),
        "brand": product.get("brands"),
        "category": product.get("categories"),
        "quantity": product.get("quantity"),
        "packaging": product.get("packaging"),
        "labels": product.get("labels"),
        "ingredients": product.get("ingredients_text"),
    }

    fields = {k: v for k, v in fields.items() if v}
    if not fields:
        return None

    return {
        "source": source,
        "url": f"https://{host}/product/{barcode}",
        "fields": fields,
        "offer_urls": [],
    }


PROVIDERS = (
    _from_upcitemdb,
    lambda bc: _from_open_facts(bc, "world.openbeautyfacts.org", "openbeautyfacts"),
    lambda bc: _from_open_facts(bc, "world.openfoodfacts.org", "openfoodfacts"),
)


def lookup_barcode(barcode):
    """Return a list of structured records for the barcode (possibly empty)."""
    barcode = re.sub(r"\D", "", str(barcode or ""))
    if len(barcode) < 8:
        return []

    cached = _read_cache(barcode)
    if cached is not None:
        return cached

    records = []
    for provider in PROVIDERS:
        try:
            record = provider(barcode)
        except Exception as exc:  # noqa: BLE001 - a bad provider must not break retrieval
            log.warning("Barcode provider error for %s: %s", barcode, exc)
            record = None
        if record:
            records.append(record)
        time.sleep(0.2)  # be polite to keyless public APIs

    _write_cache(barcode, records)
    return records


def as_evidence(records):
    """Render barcode records into the pipeline's evidence shape."""
    evidence = []
    for record in records:
        text = "; ".join(f"{k}: {v}" for k, v in record["fields"].items())
        evidence.append(
            {
                "title": record["fields"].get("title", record["source"]),
                "url": record["url"],
                "domain": record["source"],
                "snippet": text[:400],
                # Keyed on the exact barcode, so this is the strongest match
                # available short of the manufacturer's own page.
                "score": 0.95,
                "page_text": f"[{record['source']} barcode record] {text}",
            }
        )
    return evidence
