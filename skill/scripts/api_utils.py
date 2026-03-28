#!/usr/bin/env python3
"""
API utilities for TraitTrawler: retry/backoff and rate limiting.

Provides a resilient HTTP client for all external API calls (PubMed, OpenAlex,
Crossref, GBIF, Unpaywall, Europe PMC, Semantic Scholar, CORE). Handles
transient failures with exponential backoff and enforces per-API rate limits
to avoid IP bans.

Usage:
    from api_utils import resilient_fetch, RateLimiter

    # Simple fetch with retry
    data = resilient_fetch(
        "https://api.openalex.org/works/doi:10.1234/example",
        api_name="openalex"
    )

    # Manual rate limiter
    limiter = RateLimiter("pubmed", requests_per_second=3.0)
    limiter.wait()
    # ... make request ...
"""

import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Optional

logger = logging.getLogger("traittrawler.api")

# ---------------------------------------------------------------------------
# Rate limits per API (requests per second)
# ---------------------------------------------------------------------------
# Sources:
#   PubMed: 3/s with api_key, 1/s without (NCBI E-utilities policy)
#   OpenAlex: 10/s with mailto (polite pool), 1/s without
#   Crossref: 50/s with mailto (polite pool), 1/s without
#   GBIF: ~3/s (undocumented, empirically safe)
#   Unpaywall: ~1/s (rate-limited by email parameter)
#   Europe PMC: ~3/s (no documented limit, be conservative)
#   Semantic Scholar: 1/s without key, 10/s with key
#   CORE: ~1/s (no documented limit, be conservative)

RATE_LIMITS = {
    "pubmed":           {"rps": 3.0,  "note": "3/s with api_key, 1/s without"},
    "pubmed_nokey":     {"rps": 1.0,  "note": "No API key — throttled to 1/s"},
    "openalex":         {"rps": 10.0, "note": "10/s with mailto (polite pool)"},
    "openalex_nomail":  {"rps": 1.0,  "note": "No mailto — throttled to 1/s"},
    "crossref":         {"rps": 50.0, "note": "50/s with mailto (polite pool)"},
    "crossref_nomail":  {"rps": 1.0,  "note": "No mailto — throttled to 1/s"},
    "gbif":             {"rps": 3.0,  "note": "Empirically safe rate"},
    "unpaywall":        {"rps": 1.0,  "note": "Rate-limited by email param"},
    "europepmc":        {"rps": 3.0,  "note": "Conservative estimate"},
    "semantic_scholar":  {"rps": 1.0,  "note": "1/s without API key"},
    "semantic_scholar_key": {"rps": 10.0, "note": "10/s with API key"},
    "core":             {"rps": 1.0,  "note": "Conservative estimate"},
    "default":          {"rps": 1.0,  "note": "Fallback for unknown APIs"},
}


# ---------------------------------------------------------------------------
# Rate Limiter
# ---------------------------------------------------------------------------

class RateLimiter:
    """
    Per-API rate limiter using token bucket algorithm.

    Thread-safe for single-threaded async use (not multi-threaded).
    """

    _instances = {}  # class-level registry of limiters by api_name

    def __init__(self, api_name: str,
                 requests_per_second: Optional[float] = None):
        self.api_name = api_name
        if requests_per_second is not None:
            self.rps = requests_per_second
        else:
            config = RATE_LIMITS.get(api_name, RATE_LIMITS["default"])
            self.rps = config["rps"]
        self.min_interval = 1.0 / self.rps
        self._last_call = 0.0

    @classmethod
    def get(cls, api_name: str) -> "RateLimiter":
        """Get or create a rate limiter for the given API."""
        if api_name not in cls._instances:
            cls._instances[api_name] = cls(api_name)
        return cls._instances[api_name]

    def wait(self):
        """Block until it's safe to make the next request."""
        now = time.monotonic()
        elapsed = now - self._last_call
        if elapsed < self.min_interval:
            sleep_time = self.min_interval - elapsed
            time.sleep(sleep_time)
        self._last_call = time.monotonic()


# ---------------------------------------------------------------------------
# Retry with exponential backoff
# ---------------------------------------------------------------------------

# Default retry config
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0       # seconds
DEFAULT_MAX_DELAY = 16.0       # seconds
DEFAULT_BACKOFF_FACTOR = 2.0

# HTTP status codes that are retryable
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class APIError(Exception):
    """Raised when an API call fails after all retries."""

    def __init__(self, url: str, api_name: str, status_code: int = 0,
                 message: str = "", attempts: int = 0):
        self.url = url
        self.api_name = api_name
        self.status_code = status_code
        self.attempts = attempts
        super().__init__(
            f"API {api_name} failed after {attempts} attempts: "
            f"HTTP {status_code} — {message} — URL: {url}"
        )


def _parse_retry_after(value: str) -> Optional[float]:
    """Parse Retry-After header as seconds (int/float) or HTTP-date (RFC 7231)."""
    value = value.strip()
    # Try as seconds first
    try:
        return float(value)
    except ValueError:
        pass
    # Try as HTTP-date (e.g., "Wed, 21 Oct 2015 07:28:00 GMT")
    from email.utils import parsedate_to_datetime
    try:
        target = parsedate_to_datetime(value)
        from datetime import datetime, timezone
        delta = (target - datetime.now(timezone.utc)).total_seconds()
        return max(0.0, delta)
    except (ValueError, TypeError):
        return None


def resilient_fetch(url: str, api_name: str = "default",
                    headers: Optional[dict] = None,
                    timeout: int = 30,
                    max_retries: int = DEFAULT_MAX_RETRIES,
                    base_delay: float = DEFAULT_BASE_DELAY,
                    parse_json: bool = True,
                    log_file: Optional[str] = None) -> Optional[dict]:
    """
    Fetch a URL with retry/backoff and rate limiting.

    Args:
        url: The URL to fetch.
        api_name: API identifier for rate limiting (e.g., "pubmed", "openalex").
        headers: Optional HTTP headers.
        timeout: Request timeout in seconds.
        max_retries: Maximum number of retry attempts.
        base_delay: Initial delay between retries (seconds).
        parse_json: If True, parse response as JSON. If False, return raw bytes.
        log_file: Optional path to run_log.jsonl for logging retries.

    Returns:
        Parsed JSON dict (if parse_json=True), raw response bytes (if False),
        or None if all retries failed and raise_on_failure is False.

    Raises:
        APIError: If all retries are exhausted.
    """
    limiter = RateLimiter.get(api_name)

    if headers is None:
        headers = {}
    if "User-Agent" not in headers:
        headers["User-Agent"] = (
            "TraitTrawler/3.0 "
            "(autonomous literature mining; "
            "https://github.com/coleoguy/TraitTrawler)"
        )

    last_error = None

    for attempt in range(1, max_retries + 1):
        limiter.wait()

        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as response:
                data = response.read()
                if parse_json:
                    try:
                        return json.loads(data)
                    except (json.JSONDecodeError, ValueError) as je:
                        raise APIError(
                            url, api_name, response.status,
                            f"Invalid JSON response ({len(data)} bytes): "
                            f"{data[:100]!r}", attempt
                        ) from je
                return data

        except urllib.error.HTTPError as e:
            last_error = e
            status = e.code

            if status in RETRYABLE_STATUS_CODES and attempt < max_retries:
                delay = min(
                    base_delay * (DEFAULT_BACKOFF_FACTOR ** (attempt - 1)),
                    DEFAULT_MAX_DELAY
                )

                # Special handling for 429 (rate limited)
                if status == 429:
                    retry_after = e.headers.get("Retry-After", "")
                    if retry_after:
                        retry_delay = _parse_retry_after(retry_after)
                        if retry_delay is not None:
                            delay = max(delay, retry_delay)

                _log_retry(api_name, url, status, attempt, max_retries,
                           delay, log_file)
                logger.warning(
                    f"[{api_name}] HTTP {status} on attempt {attempt}/"
                    f"{max_retries}. Retrying in {delay:.1f}s..."
                )
                time.sleep(delay)
                continue
            else:
                # Non-retryable or exhausted retries
                msg = f"HTTP {status}"
                try:
                    msg += f": {e.read().decode('utf-8', errors='replace')[:200]}"
                except Exception:
                    pass
                raise APIError(url, api_name, status, msg, attempt) from e

        except urllib.error.URLError as e:
            last_error = e
            if attempt < max_retries:
                delay = min(
                    base_delay * (DEFAULT_BACKOFF_FACTOR ** (attempt - 1)),
                    DEFAULT_MAX_DELAY
                )
                _log_retry(api_name, url, 0, attempt, max_retries,
                           delay, log_file)
                logger.warning(
                    f"[{api_name}] Connection error on attempt {attempt}/"
                    f"{max_retries}: {e.reason}. Retrying in {delay:.1f}s..."
                )
                time.sleep(delay)
                continue
            else:
                raise APIError(url, api_name, 0, str(e.reason),
                               attempt) from e

        except (TimeoutError, OSError) as e:
            last_error = e
            if attempt < max_retries:
                delay = min(
                    base_delay * (DEFAULT_BACKOFF_FACTOR ** (attempt - 1)),
                    DEFAULT_MAX_DELAY
                )
                _log_retry(api_name, url, 0, attempt, max_retries,
                           delay, log_file)
                logger.warning(
                    f"[{api_name}] Timeout on attempt {attempt}/"
                    f"{max_retries}. Retrying in {delay:.1f}s..."
                )
                time.sleep(delay)
                continue
            else:
                raise APIError(url, api_name, 0, f"Timeout: {e}",
                               attempt) from e

    # Should not reach here, but just in case
    raise APIError(url, api_name, 0,
                   f"All {max_retries} retries exhausted: {last_error}",
                   max_retries)


def _log_retry(api_name: str, url: str, status: int, attempt: int,
               max_retries: int, delay: float,
               log_file: Optional[str] = None):
    """Append a retry event to run_log.jsonl if path is provided."""
    if not log_file:
        return
    try:
        entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": "api_retry",
            "api": api_name,
            "url": url[:200],
            "status": status,
            "attempt": attempt,
            "max_retries": max_retries,
            "delay_seconds": round(delay, 1),
        }
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as log_err:
        # Log to stderr so disk/permission issues are visible
        try:
            print(f"WARNING: Failed to write retry log: {log_err}",
                  file=sys.stderr)
        except Exception:
            pass  # truly last-resort — never interrupt the pipeline


# ---------------------------------------------------------------------------
# Convenience wrappers for common APIs
# ---------------------------------------------------------------------------

def fetch_unpaywall(doi: str, email: str,
                    log_file: Optional[str] = None) -> Optional[dict]:
    """Fetch Unpaywall metadata for a DOI."""
    url = f"https://api.unpaywall.org/v2/{doi}?email={email}"
    return resilient_fetch(url, api_name="unpaywall", log_file=log_file)


def fetch_openalex_work(doi: str, email: str,
                        log_file: Optional[str] = None) -> Optional[dict]:
    """Fetch OpenAlex work metadata by DOI."""
    url = (
        f"https://api.openalex.org/works/doi:{doi}"
        f"?select=best_oa_location,open_access&mailto={email}"
    )
    api = "openalex" if email else "openalex_nomail"
    return resilient_fetch(url, api_name=api, log_file=log_file)


def fetch_europepmc(doi: str,
                    log_file: Optional[str] = None) -> Optional[dict]:
    """Search Europe PMC for a DOI."""
    url = (
        f"https://www.ebi.ac.uk/europepmc/webservices/rest/search"
        f"?query=DOI:{doi}&resultType=lite&format=json"
    )
    return resilient_fetch(url, api_name="europepmc", log_file=log_file)


def fetch_semantic_scholar(doi: str,
                           log_file: Optional[str] = None) -> Optional[dict]:
    """Fetch Semantic Scholar paper by DOI."""
    url = (
        f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}"
        f"?fields=openAccessPdf"
    )
    return resilient_fetch(url, api_name="semantic_scholar",
                           log_file=log_file)


def fetch_core(doi: str,
               log_file: Optional[str] = None) -> Optional[dict]:
    """Search CORE for a DOI."""
    url = f"https://api.core.ac.uk/v3/search/works?q=doi:{doi}&limit=1"
    return resilient_fetch(url, api_name="core", log_file=log_file)


def fetch_gbif_species(name: str, kingdom: str = "Animalia",
                       log_file: Optional[str] = None) -> Optional[dict]:
    """Match a species name against GBIF Backbone Taxonomy."""
    import urllib.parse
    url = (
        f"https://api.gbif.org/v1/species/match"
        f"?name={urllib.parse.quote(name)}&kingdom={kingdom}&verbose=true"
    )
    return resilient_fetch(url, api_name="gbif", log_file=log_file)


# ---------------------------------------------------------------------------
# Rate limit summary for documentation
# ---------------------------------------------------------------------------

def print_rate_limits():
    """Print a table of all configured rate limits."""
    print(f"{'API':<25} {'Req/sec':<10} {'Min interval':<15} {'Notes'}")
    print("-" * 80)
    for name, config in sorted(RATE_LIMITS.items()):
        rps = config["rps"]
        interval = 1.0 / rps
        note = config["note"]
        print(f"{name:<25} {rps:<10.1f} {interval:<15.3f}s {note}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="TraitTrawler API utilities"
    )
    parser.add_argument("--rate-limits", action="store_true",
                        help="Print configured rate limits")
    parser.add_argument("--test-url",
                        help="Test resilient_fetch with a URL")
    parser.add_argument("--api-name", default="default",
                        help="API name for rate limiting (with --test-url)")
    args = parser.parse_args()

    if args.rate_limits:
        print_rate_limits()
    elif args.test_url:
        try:
            result = resilient_fetch(args.test_url, api_name=args.api_name)
            print(json.dumps(result, indent=2)[:2000])
        except APIError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
