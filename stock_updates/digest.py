"""Build the digest email (subject, HTML body, plain-text body) from digest.json.

digest.json is authored by the routine (summaries in its own words) and only
contains NON-baseline items; baseline tickers appear in `baseline_tickers`.
See RUNBOOK.md for the full schema.
"""

import html as html_mod
from datetime import date, datetime

from . import config


def _digest_date(data, tz):
    raw = (data.get("date") or "").strip()
    if raw:
        try:
            return date.fromisoformat(raw)
        except ValueError:
            print(f"WARNING: ignoring invalid digest date {raw!r}")
    return datetime.now(tz).date()


def _plural(n, noun):
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def _sorted_items(items):
    """EDGAR items before web items, otherwise preserving the given order."""
    return sorted(items, key=lambda i: 0 if i.get("source") == "edgar" else 1)


def _company_heading(company):
    ticker = (company.get("ticker") or "").strip()
    name = (company.get("company") or "").strip()
    return f"{ticker} — {name}" if ticker else name


def _item_label(item):
    """e.g. '[EDGAR] 8-K (2026-06-03)' or '[web] Reuters (2026-06-02)'."""
    if item.get("source") == "edgar":
        prefix = f"[EDGAR] {item.get('item_type') or 'filing'}"
    else:
        prefix = f"[web] {item.get('publication') or 'news'}"
    event_date = (item.get("event_date") or "").strip()
    return f"{prefix} ({event_date})" if event_date else prefix


def build(data, heartbeat=False):
    """Return (subject, html_body, text_body)."""
    tz = config.get_timezone()
    day = _digest_date(data, tz)

    companies = [c for c in data.get("companies", []) if c.get("items")]
    total = sum(len(c["items"]) for c in companies)
    baseline_tickers = data.get("baseline_tickers") or []
    errors = data.get("errors") or []
    tracked = data.get("tracked_tickers") or []

    # Uniform subject every day (user preference); the body header carries
    # the counts, and a no-news day reads "No updates today." in the body.
    subject = f"Stock Tracker Daily Update: {day:%B} {day.day}, {day.year}"

    text_lines = []
    html_parts = []

    if total:
        header = (
            f"stock_updates for {day:%b} {day.day}, {day.year} — "
            f"{_plural(total, 'new update')} across {_plural(len(companies), 'ticker')}."
        )
        text_lines.append(header)
        html_parts.append(f"<p>{html_mod.escape(header)}</p>")
        for company in companies:
            heading = _company_heading(company)
            text_lines.append("")
            text_lines.append(heading)
            text_lines.append("=" * len(heading))
            html_parts.append(f"<h3 style=\"margin:14px 0 2px\">{html_mod.escape(heading)}</h3>")
            for item in _sorted_items(company["items"]):
                label = _item_label(item)
                headline = (item.get("headline") or "").strip()
                # summary may be one or more paragraphs (newline-separated);
                # major filings warrant up to two — see RUNBOOK "Summarize".
                summary = (item.get("summary") or headline or "").strip()
                paragraphs = [p.strip() for p in summary.splitlines() if p.strip()]
                if not paragraphs:
                    continue
                url = (item.get("url") or "").strip()
                focus = (item.get("focus_area") or "").strip()
                # the label already names the form — don't repeat it in the title
                item_type = (item.get("item_type") or "").strip()
                if headline and item_type and headline.upper().startswith(item_type.upper()):
                    headline = headline[len(item_type):].lstrip(" —–-:").strip()
                    if headline.lower() == "filing":
                        headline = ""
                title = f"{label} — {headline}" if headline else label

                text_lines.append("")
                text_lines.append(f"{title}{f'  [{focus}]' if focus else ''}")
                for para in paragraphs:
                    text_lines.append(f"  {para}")
                if url:
                    text_lines.append(f"  source: {url}")

                focus_html = f" <em>[{html_mod.escape(focus)}]</em>" if focus else ""
                html_parts.append(
                    f"<p style=\"margin:10px 0 2px\"><strong>{html_mod.escape(title)}</strong>"
                    f"{focus_html}</p>"
                )
                body = [
                    f"<p style=\"margin:4px 0\">{html_mod.escape(p)}</p>" for p in paragraphs
                ]
                if url:
                    link = f' <a href="{html_mod.escape(url, quote=True)}">[source]</a>'
                    body[-1] = body[-1][:-len("</p>")] + link + "</p>"
                html_parts.extend(body)
    else:
        text_lines.append("No updates today.")
        html_parts.append("<p>No updates today.</p>")
        if tracked:
            tracked_line = "Tracking: " + ", ".join(tracked)
            text_lines.append(tracked_line)
            html_parts.append(f"<p>{html_mod.escape(tracked_line)}</p>")

    footer_lines = []
    for ticker in baseline_tickers:
        footer_lines.append(
            f"Now tracking {ticker} — recent history was recorded as a baseline; "
            "new items will be emailed starting tomorrow."
        )
    for err in errors:
        who = err.get("company") or err.get("ticker") or "a company"
        reason = err.get("reason") or "unknown error"
        footer_lines.append(f"Couldn't check {who} today ({reason}).")
    if heartbeat:
        footer_lines.append("Heartbeat: routine healthy — this run completed normally.")

    if footer_lines:
        text_lines.append("")
        text_lines.extend(footer_lines)
        html_parts.append(
            "<p>" + "<br>".join(html_mod.escape(line) for line in footer_lines) + "</p>"
        )

    html_body = (
        '<div style="font-family: -apple-system, Segoe UI, Helvetica, Arial, '
        'sans-serif; font-size: 14px; line-height: 1.5;">'
        + "".join(html_parts)
        + "</div>"
    )
    return subject, html_body, "\n".join(text_lines) + "\n"
