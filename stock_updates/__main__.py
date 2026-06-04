"""CLI for stock_updates.

Subcommands (see RUNBOOK.md for how a scheduled run chains them):
  check-env    validate required environment variables
  fetch-edgar  new material SEC filings per watchlist company (deduped)
  dedup-web    compute keys for web findings and drop already-ledgered ones
  send-email   build + send the consolidated digest (or --dry-run)

All progress is logged to stdout; data moves between steps as JSON files.
"""

import argparse
import json
import sys
from datetime import datetime, timedelta

from . import config, dedup, digest, emailer, sec, watchlist


def _read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"wrote {path}")


# --- check-env ---------------------------------------------------------------

def cmd_check_env(args):
    missing = config.missing_env_vars()
    for name in config.REQUIRED_ENV_VARS:
        print(f"  {name}: {'MISSING' if name in missing else 'ok'}")
    tz_note = "" if config.env("TIMEZONE") else " (default)"
    print(f"  TIMEZONE: {config.get_timezone_name()}{tz_note}")
    if missing:
        print(f"ERROR: missing required environment variables: {', '.join(missing)}")
        return 1
    print("environment OK")
    return 0


# --- fetch-edgar -------------------------------------------------------------

def _fetch_company_filings(session, ticker_map, entry, ledger, today, args):
    """EDGAR results for one watchlist entry. Raises on unexpected errors."""
    result = {
        "ticker": entry["ticker"],
        "company": entry["company"],
        "ledger_ticker": entry["ledger_ticker"],
        "focus_areas": entry["focus_areas"],
        "baseline": not ledger.knows_ticker(entry["ledger_ticker"]),
        "lookback_days": None,
        "edgar_skipped": None,
        "items": [],
    }
    baseline_tag = " [baseline]" if result["baseline"] else ""
    display = (
        f"{entry['ticker']} ({entry['company']})" if entry["ticker"] else entry["company"]
    )

    cik = entry.get("cik")  # explicit watchlist cik wins over ticker-map lookup
    if cik is None:
        if not entry["ticker"]:
            result["edgar_skipped"] = "no ticker or cik — web-only"
            print(f"{display}: no ticker or cik; skipping EDGAR (web-only){baseline_tag}")
            return result
        cik = ticker_map.get(entry["ticker"])
        if cik is None:
            result["edgar_skipped"] = f"no CIK match for ticker {entry['ticker']}"
            print(f"{display}: no CIK match; skipping EDGAR (web-only){baseline_tag}")
            return result

    lookback = args.baseline_days if result["baseline"] else args.lookback_days
    result["lookback_days"] = lookback
    since = (today - timedelta(days=lookback)).isoformat()

    filings = sec.recent_filings(session, cik, since)
    new = [f for f in filings if not ledger.has_key(f["accession"])]

    excerpts_fetched = 0
    for filing in new:
        # Baseline items are ledgered but never summarized/emailed — skip the
        # excerpt fetches and keep first runs fast.
        excerpt = ""
        if not result["baseline"] and excerpts_fetched < config.EXCERPT_FETCH_LIMIT:
            excerpt = sec.fetch_filing_excerpt(session, cik, filing)
            excerpts_fetched += 1
        description = filing["description"]
        if description.upper() == filing["form"]:  # e.g. "8-K — 8-K" is noise
            description = ""
        headline = filing["form"] + (f" — {description}" if description else " filing")
        result["items"].append({
            "key": filing["accession"],
            "ticker": entry["ledger_ticker"],
            "source": "edgar",
            "item_type": filing["form"],
            "headline": headline,
            "url": sec.filing_index_url(cik, filing["accession"]),
            "event_date": filing["filing_date"],
            "baseline": result["baseline"],
            "excerpt": excerpt,
        })

    print(
        f"{display}: {len(filings)} material filings in last {lookback}d, "
        f"{len(new)} new{baseline_tag}"
    )
    return result


def cmd_fetch_edgar(args):
    user_agent = config.require_env("SEC_USER_AGENT")
    companies = watchlist.load_watchlist(args.watchlist)
    ledger = dedup.Ledger.from_file(args.ledger)
    print(f"watchlist: {len(companies)} companies; ledger: {ledger.row_count} rows")

    session = sec.SecSession(user_agent)
    today = datetime.now(config.get_timezone()).date()
    ticker_map = None
    results, errors = [], []

    for entry in companies:
        try:
            if ticker_map is None and entry["ticker"] and not entry.get("cik"):
                ticker_map = sec.load_ticker_map(session)
            results.append(
                _fetch_company_filings(session, ticker_map or {}, entry, ledger, today, args)
            )
        except Exception as exc:  # one company's failure must not abort the run
            reason = f"{type(exc).__name__}: {exc}"
            print(f"{entry['company']}: EDGAR check FAILED — {reason}")
            errors.append({
                "ticker": entry["ticker"],
                "company": entry["company"],
                "reason": reason,
            })

    total_new = sum(len(r["items"]) for r in results)
    total_baseline = sum(len(r["items"]) for r in results if r["baseline"])
    print(
        f"EDGAR totals: {total_new} new items "
        f"({total_baseline} baseline, {total_new - total_baseline} emailable), "
        f"{len(errors)} company errors"
    )
    _write_json(args.out, {
        "run_date": today.isoformat(),
        "lookback_days": args.lookback_days,
        "baseline_days": args.baseline_days,
        "companies": results,
        "errors": errors,
    })
    return 0


# --- dedup-web ---------------------------------------------------------------

def cmd_dedup_web(args):
    ledger = dedup.Ledger.from_file(args.ledger)
    items = _read_json(args.items).get("items") or []

    kept, dropped, skipped = [], 0, 0
    seen_urls, seen_headlines = set(), set()
    for item in items:
        url = (item.get("url") or "").strip()
        headline = (item.get("headline") or "").strip()
        if not url:
            skipped += 1
            print(f"  skipping item with no url: {headline[:80]!r}")
            continue
        key = dedup.web_url_key(url)
        hkey = dedup.headline_key(headline)
        if ledger.has_key(key) or key in seen_urls:
            dropped += 1
            continue
        if headline and (ledger.has_headline(headline) or hkey in seen_headlines):
            dropped += 1
            continue
        seen_urls.add(key)
        seen_headlines.add(hkey)
        ledger_ticker = (item.get("ticker") or item.get("company") or "").strip()
        kept.append({
            "key": key,
            "ticker": ledger_ticker,
            "source": "web",
            "item_type": "news",
            "headline": headline,
            "url": url,
            "event_date": (item.get("date") or item.get("event_date") or "").strip(),
            "baseline": not ledger.knows_ticker(ledger_ticker),
            "publication": (item.get("publication") or "").strip(),
        })

    print(
        f"web dedup: {len(items)} in, {len(kept)} new, "
        f"{dropped} already seen, {skipped} skipped (no url)"
    )
    _write_json(args.out, {"items": kept})
    return 0


# --- send-email --------------------------------------------------------------

def cmd_send_email(args):
    data = _read_json(args.digest)
    subject, html_body, text_body = digest.build(data, heartbeat=args.heartbeat)
    print(f"subject: {subject}")

    if args.dry_run:
        sender = config.env("SENDER_EMAIL") or "<SENDER_EMAIL>"
        recipient = config.env("RECIPIENT_EMAIL") or "<RECIPIENT_EMAIL>"
        print(f"DRY RUN — not sending. Would send from {sender} to {recipient}.")
        print("--- text body " + "-" * 50)
        print(text_body)
        print("--- html body " + "-" * 50)
        print(html_body)
        return 0

    result = emailer.send(
        api_key=config.require_env("EMAIL_API_KEY"),
        sender=config.require_env("SENDER_EMAIL"),
        recipient=config.require_env("RECIPIENT_EMAIL"),
        subject=subject,
        html_body=html_body,
        text_body=text_body,
    )
    print(f"email sent (provider id: {result.get('id', 'unknown')})")
    return 0


# --- parser ------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog="python -m stock_updates",
        description="stock_updates CLI — see RUNBOOK.md for the full run flow",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("check-env", help="validate required environment variables")
    p.set_defaults(func=cmd_check_env)

    p = sub.add_parser("fetch-edgar", help="fetch new material SEC filings (deduped)")
    p.add_argument("--watchlist", default="watchlist.yaml")
    p.add_argument("--ledger", required=True, help="ledger.json exported from Notion")
    p.add_argument("--out", required=True, help="where to write edgar_new.json")
    p.add_argument("--lookback-days", type=int, default=config.DEFAULT_LOOKBACK_DAYS)
    p.add_argument("--baseline-days", type=int, default=config.DEFAULT_BASELINE_DAYS)
    p.set_defaults(func=cmd_fetch_edgar)

    p = sub.add_parser("dedup-web", help="key + dedup web findings against the ledger")
    p.add_argument("--items", required=True, help="web_items.json from the web search step")
    p.add_argument("--ledger", required=True, help="ledger.json exported from Notion")
    p.add_argument("--out", required=True, help="where to write web_new.json")
    p.set_defaults(func=cmd_dedup_web)

    p = sub.add_parser("send-email", help="build and send the digest email")
    p.add_argument("--digest", required=True, help="digest.json with authored summaries")
    p.add_argument("--dry-run", action="store_true", help="print instead of sending")
    p.add_argument("--heartbeat", action="store_true", help="append the weekly health footer")
    p.set_defaults(func=cmd_send_email)

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except SystemExit:
        raise
    except Exception as exc:  # fail loudly — session logs are the debugging surface
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
