"""Load and validate watchlist.yaml."""

import yaml


class WatchlistError(ValueError):
    """watchlist.yaml is malformed."""


def load_watchlist(path):
    """Return a list of {ticker, company, cik, focus_areas, ledger_ticker} dicts.

    `ticker` is uppercased, or None for a private company (tracked web-only
    unless `cik` is given). `cik` is an optional explicit SEC CIK that
    overrides ticker-map resolution (pre-IPO tickers, private filers).
    `ledger_ticker` is the value used in the Notion ledger's `ticker` field:
    the ticker if present, otherwise the company name.
    """
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict) or not isinstance(data.get("companies"), list):
        raise WatchlistError(f"{path}: expected a top-level 'companies:' list")

    companies = []
    for i, entry in enumerate(data["companies"]):
        where = f"{path}: companies[{i}]"
        if not isinstance(entry, dict):
            raise WatchlistError(f"{where} is not a mapping")
        company = entry.get("company")
        if not isinstance(company, str) or not company.strip():
            raise WatchlistError(f"{where} is missing 'company'")
        company = company.strip()
        if "ticker" not in entry:
            raise WatchlistError(f"{where} ({company}) is missing 'ticker' (use null for none)")
        ticker = entry["ticker"]
        if ticker is not None:
            if not isinstance(ticker, str) or not ticker.strip():
                raise WatchlistError(f"{where} ({company}) has an invalid ticker")
            ticker = ticker.strip().upper()
        cik = entry.get("cik")
        if cik is not None:
            if isinstance(cik, str) and cik.strip().isdigit():
                cik = int(cik.strip())
            if isinstance(cik, bool) or not isinstance(cik, int) or cik <= 0:
                raise WatchlistError(f"{where} ({company}) cik must be a positive integer")
        focus_areas = entry.get("focus_areas") or []
        if not isinstance(focus_areas, list) or not all(
            isinstance(x, str) and x.strip() for x in focus_areas
        ):
            raise WatchlistError(f"{where} ({company}) focus_areas must be a list of strings")
        companies.append({
            "ticker": ticker,
            "company": company,
            "cik": cik,
            "focus_areas": [x.strip() for x in focus_areas],
            "ledger_ticker": ticker or company,
        })

    if not companies:
        raise WatchlistError(f"{path}: watchlist has no companies")
    return companies
