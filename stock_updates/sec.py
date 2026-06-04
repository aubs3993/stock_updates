"""SEC EDGAR access: ticker→CIK, recent filings, filing excerpts.

All requests go through SecSession, which sends the required User-Agent,
paces itself well under SEC's 10 requests/second limit, and backs off on 429.
"""

import re
import time
from html.parser import HTMLParser

import requests

from . import config


class SecSession:
    """requests.Session wrapper enforcing SEC fair-access rules."""

    def __init__(self, user_agent):
        self._session = requests.Session()
        self._session.headers["User-Agent"] = user_agent
        self._session.headers["Accept-Encoding"] = "gzip, deflate"
        self._last_request = 0.0

    def get(self, url):
        for attempt in range(config.SEC_MAX_RETRIES + 1):
            self._pace()
            resp = self._session.get(url, timeout=config.SEC_TIMEOUT_SECONDS)
            if resp.status_code == 429:
                wait = 2 ** attempt
                print(f"  SEC 429 on {url}; backing off {wait}s")
                time.sleep(wait)
                continue
            if resp.status_code == 403:
                raise RuntimeError(
                    f"SEC returned 403 for {url} — SEC_USER_AGENT must look like "
                    "'Name email@example.com'"
                )
            resp.raise_for_status()
            return resp
        raise RuntimeError(
            f"SEC kept returning 429 after {config.SEC_MAX_RETRIES} retries: {url}"
        )

    def _pace(self):
        elapsed = time.monotonic() - self._last_request
        if elapsed < config.SEC_REQUEST_INTERVAL_SECONDS:
            time.sleep(config.SEC_REQUEST_INTERVAL_SECONDS - elapsed)
        self._last_request = time.monotonic()


def load_ticker_map(session):
    """Return {TICKER: cik_int} from SEC's company_tickers.json (fetch once per run)."""
    data = session.get(config.SEC_TICKER_MAP_URL).json()
    return {row["ticker"].upper(): int(row["cik_str"]) for row in data.values()}


def is_material_form(form):
    base = (form or "").strip().upper()
    if base.endswith("/A"):
        base = base[:-2].strip()
    return base in config.MATERIAL_FORMS or base.startswith(config.MATERIAL_FORM_PREFIXES)


def recent_filings(session, cik, since_date):
    """Material filings from filings.recent filed on/after since_date (ISO yyyy-mm-dd).

    Returns dicts: {accession, form, filing_date, primary_document, description}.
    """
    url = config.SEC_SUBMISSIONS_URL.format(cik=cik)
    recent = session.get(url).json().get("filings", {}).get("recent", {})
    accessions = recent.get("accessionNumber", [])

    def col(name):
        values = recent.get(name) or []
        return values if len(values) == len(accessions) else [""] * len(accessions)

    forms, dates = col("form"), col("filingDate")
    primary_docs, descriptions = col("primaryDocument"), col("primaryDocDescription")

    out = []
    for i, accession in enumerate(accessions):
        if dates[i] < since_date or not is_material_form(forms[i]):
            continue
        out.append({
            "accession": accession,
            "form": forms[i].strip().upper(),
            "filing_date": dates[i],
            "primary_document": primary_docs[i],
            "description": (descriptions[i] or "").strip(),
        })
    return out


def filing_index_url(cik, accession):
    """Human-friendly filing index page on sec.gov."""
    nodash = accession.replace("-", "")
    return f"{config.SEC_ARCHIVES_BASE}/{cik}/{nodash}/{accession}-index.htm"


class _TextExtractor(HTMLParser):
    """Collect visible text, skipping script/style/head content."""

    # ix:header holds hidden inline-XBRL metadata that pollutes excerpts
    _SKIP_TAGS = {"script", "style", "head", "title", "ix:header"}

    def __init__(self):
        super().__init__()
        self.chunks = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self._SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if not self._skip_depth:
            self.chunks.append(data)


def html_to_text(html):
    parser = _TextExtractor()
    parser.feed(html)
    return re.sub(r"\s+", " ", "".join(parser.chunks)).strip()


def fetch_filing_excerpt(session, cik, filing):
    """Fetch the filing's primary document and return a truncated plain-text excerpt.

    Returns "" on any failure — an excerpt is a nice-to-have, never fatal.
    """
    primary = filing.get("primary_document")
    if not primary:
        return ""
    nodash = filing["accession"].replace("-", "")
    url = f"{config.SEC_ARCHIVES_BASE}/{cik}/{nodash}/{primary}"
    try:
        text = html_to_text(session.get(url).text)
    except Exception as exc:
        print(f"  warning: could not fetch excerpt for {filing['accession']}: {exc}")
        return ""
    if len(text) > config.EXCERPT_MAX_CHARS:
        text = text[:config.EXCERPT_MAX_CHARS] + " …[truncated]"
    return text
