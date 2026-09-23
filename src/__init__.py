"""Product Truth Agent package.

Configures TLS trust at import time. Corporate networks that intercept TLS
(Netskope, Zscaler, etc.) present a root CA that lives in the OS trust store
but not in certifi's bundle, which is what `requests` and the Azure SDK use by
default. `truststore` makes Python use the OS store instead, so no manual
certificate wrangling is needed.

Escape hatches:
  REQUESTS_CA_BUNDLE / SSL_CERT_FILE  point at an explicit PEM bundle
  PTA_INSECURE_SSL=1                  disable verification (prototyping only)
"""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Explicit path: a bare load_dotenv() resolves relative to the caller's file
# and fails outright when there is no calling frame, so `.env` would be missed
# whenever the package is driven from another working directory.
load_dotenv(PROJECT_ROOT / ".env")


def _configure_tls():
    if os.getenv("PTA_INSECURE_SSL", "").strip().lower() in {"1", "true", "yes"}:
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        log.warning("PTA_INSECURE_SSL is set: TLS verification is DISABLED.")
        return

    if os.getenv("REQUESTS_CA_BUNDLE") or os.getenv("SSL_CERT_FILE"):
        return

    try:
        import truststore

        truststore.inject_into_ssl()
    except ImportError:
        log.debug("truststore not installed; using certifi's CA bundle.")


_configure_tls()
