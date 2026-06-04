"""Dedup keys and ledger filtering.

Keys (see CLAUDE.md "Dedup"):
- EDGAR: the filing accession number (globally unique) — used as-is.
- Web:   sha1 of the normalized URL. To catch the same event reported by a
  second source, a secondary headline key is also compared; it is recomputed
  from the `headline` column of web-source ledger rows, so it survives across
  stateless runs without extra ledger columns.
"""

import hashlib
import json
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Query parameters that identify tracking campaigns, not content.
_TRACKING_PARAMS = {
    "fbclid", "gclid", "gclsrc", "dclid", "msclkid", "twclid", "igshid",
    "mc_cid", "mc_eid", "cmpid", "ncid", "ito", "smid", "sref", "src",
}


def _is_tracking_param(name):
    return name.lower().startswith("utm_") or name.lower() in _TRACKING_PARAMS


def normalize_url(url):
    """Lowercase host, strip tracking params, drop fragment, trim trailing /."""
    parts = urlsplit(url.strip())
    scheme = (parts.scheme or "https").lower()
    netloc = parts.netloc.lower()
    path = parts.path.rstrip("/") or "/"
    query = urlencode(
        [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
         if not _is_tracking_param(k)]
    )
    return urlunsplit((scheme, netloc, path, query, ""))


def web_url_key(url):
    """Primary dedup key for a web item: sha1 of the normalized URL."""
    return hashlib.sha1(normalize_url(url).encode("utf-8")).hexdigest()


def headline_key(headline):
    """Secondary dedup key: sha1 of the whitespace-collapsed, lowercased headline."""
    normalized = re.sub(r"\s+", " ", (headline or "").strip().lower())
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


class Ledger:
    """In-memory view of the Notion ledger export (ledger.json).

    Expected shape: {"rows": [{"key": ..., "ticker": ..., "source": ...,
    "headline": ...}, ...]} — `source` and `headline` are optional but enable
    the secondary headline dedup for web items.
    """

    def __init__(self, rows):
        self.row_count = len(rows)
        self.keys = {r["key"] for r in rows if r.get("key")}
        self._tickers = {(r.get("ticker") or "").strip().upper() for r in rows}
        self._headline_keys = {
            headline_key(r["headline"])
            for r in rows
            if r.get("source") == "web" and r.get("headline")
        }

    @classmethod
    def from_file(cls, path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        rows = data.get("rows")
        if not isinstance(rows, list):
            raise ValueError(f"{path}: expected a JSON object with a 'rows' list")
        return cls(rows)

    def has_key(self, key):
        return key in self.keys

    def has_headline(self, headline):
        return bool(headline) and headline_key(headline) in self._headline_keys

    def knows_ticker(self, ledger_ticker):
        """True if the ticker has any ledger rows (i.e., is past its baseline)."""
        return (ledger_ticker or "").strip().upper() in self._tickers
