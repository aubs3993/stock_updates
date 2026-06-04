# RUNBOOK.md — how a scheduled run executes

This file is the per-run orchestration contract. `CLAUDE.md` defines *what*
the project does; this file defines *exactly how* each daily routine run does
it, so every run executes the same way instead of improvising.

## Division of labor

The runtime has no Notion API key and no web-search API key — those are only
reachable through the routine's **connectors**. So each run is a hybrid:

| Who | Does |
|---|---|
| **Python** (`python -m stock_updates …`) | EDGAR fetching (rate-limited, User-Agent), dedup-key computation + ledger filtering, email subject/body construction, Resend send, all stdout logging |
| **Claude** (you, the routine) | Notion reads/writes via the Notion connector, web search via the web-search/Exa connector, writing summaries in your own words, chaining the steps below |

Data moves between steps as JSON files in a scratch directory **outside the
repo** (e.g. `/tmp/su/`). Never commit or push anything; the repo is read-only
input.

## The run, step by step

### 0. Setup
```
pip install -r requirements.txt
python -m stock_updates check-env
```
If `check-env` fails, stop and fail loudly — the session log is the alert.

### 1. Read the persistent store (Notion connector)
Under the page `NOTION_PARENT_PAGE_ID`:

1. Find the database titled **"stock_updates ledger"**. If missing (first run),
   create it with exactly these properties:
   `key` (title), `ticker` (text), `source` (select: `edgar` | `web`),
   `item_type` (text), `headline` (text), `url` (url), `event_date` (date),
   `first_seen` (date).
2. Find (don't create yet) the per-ticker child pages titled `TICKER — Company`.
3. Export **all** ledger rows (paginate to the end) to `/tmp/su/ledger.json`:

```json
{"rows": [{"key": "...", "ticker": "SATS", "source": "edgar|web", "headline": "..."}]}
```

`source` and `headline` matter: they let Python recompute the secondary
headline dedup key for web items. On a true first run this is `{"rows": []}`.

### 2. EDGAR (Python)
```
python -m stock_updates fetch-edgar --watchlist watchlist.yaml \
    --ledger /tmp/su/ledger.json --out /tmp/su/edgar_new.json
```
This resolves tickers→CIKs (an explicit `cik` in the watchlist wins), pulls
`data.sec.gov` submissions, filters to
material forms within the lookback window (7 days; 30 days for **baseline**
tickers — those with zero ledger rows), drops already-ledgered accession
numbers, and attaches a plain-text `excerpt` of each new non-baseline filing
for you to summarize from. Per-company errors land in `errors` — they never
abort the run.

### 3. Web search (connector) + dedup (Python)
For each company in `edgar_new.json`'s `companies` list: search the web for
important news from the last `lookback_days` days (the field is per-company:
30 on baseline runs, else 7), guided by its `focus_areas` (or the default
focus areas in `CLAUDE.md`). Prefer primary and reputable sources. Collect
candidates into `/tmp/su/web_items.json`:

```json
{"items": [{"ticker": "SATS", "company": "EchoStar Corporation",
            "url": "...", "headline": "...", "publication": "Reuters",
            "date": "2026-06-04"}]}
```

For a private company (`ticker: null`), set `"ticker"` to the company name.
Then:
```
python -m stock_updates dedup-web --items /tmp/su/web_items.json \
    --ledger /tmp/su/ledger.json --out /tmp/su/web_new.json
```
Python normalizes URLs (lowercase host, strip `utm_*`/tracking params, drop
fragments), hashes them, also drops items whose headline matches an existing
web ledger row, and marks baseline items. If a web-search connector call fails
for a company, add it to the digest's `errors` instead of failing the run.

### 4. Summarize (you) → digest.json
From `edgar_new.json` + `web_new.json`, build `/tmp/su/digest.json`:

```json
{
  "date": "2026-06-04",
  "companies": [
    {"ticker": "SATS", "company": "EchoStar Corporation",
     "items": [{"source": "edgar", "item_type": "8-K", "headline": "...",
                "summary": "1-2 lines, in your own words",
                "url": "...", "event_date": "2026-06-03",
                "focus_area": "Capital structure & financing",
                "publication": null}]}
  ],
  "baseline_tickers": ["NVDA"],
  "errors": [{"ticker": null, "company": "X", "reason": "..."}],
  "tracked_tickers": ["SATS", "NVDA"]
}
```

Rules:
- **Only non-baseline items** go in `companies[].items`. Items flagged
  `"baseline": true` are *not* summarized or emailed — their tickers go in
  `baseline_tickers` instead ("Now tracking …" line).
- Summaries are concise (1–2 lines), **in your own words**, never pasted
  article/filing text. Tag a `focus_area` where one clearly applies.
- Companies with no new items are simply omitted.
- `errors` = EDGAR errors from step 2 plus any web-search failures.
- `tracked_tickers` = every watchlist entry (shown on no-update days).

### 5. Send the email (Python)
```
python -m stock_updates send-email --digest /tmp/su/digest.json
```
Add `--heartbeat` if today is **Monday** in `TIMEZONE` (the weekly health
footer). Subject and body formatting (including the "no updates" day) are
handled by Python per the spec.

**Check the exit code.** Non-zero = the email did not send → **stop here. Do
not write anything to Notion.** The items stay un-ledgered and will be picked
up again tomorrow (that's the intended retry).

### 6. Persist to Notion (connector) — only after a successful send
Write **every** item from `edgar_new.json` and `web_new.json` — including
baseline items — to the ledger database, one row each, mapping fields 1:1
(`key`→title, `ticker`, `source`, `item_type`, `headline`, `url`,
`event_date`) and setting `first_seen` to today.

Then append to each affected ticker's child page (`TICKER — Company`; create
it under `NOTION_PARENT_PAGE_ID` if missing, using the format below), newest
at the top, one short line per item: date, source, headline, your one-line
summary, link. For a baseline batch, a single compact "Baseline recorded — N
filings / M articles (dates …)" block is enough. Do not paste full article or
filing text. After appending, surgically update the page's top **dossier**
where the day's items affect it — Financials & Metrics, the Notes & Links
timeline, and the Overview paragraph for genuinely material changes
(deal closed, IPO priced, leadership change) — bump its last-updated date,
and otherwise leave it alone.

### 7. Log the outcome
Finish the session log with one summary line, e.g.:
`done: 3 emailed (SATS 2, NVDA 1), 14 baseline ledgered, 0 errors, email sent, 17 ledger rows written`.

## Onboarding a new company (baseline at add-time)

When a company is added to `watchlist.yaml` in an interactive Claude Code
session, don't make it wait for the next scheduled run — onboard it in the
same session (the scheduled run's automatic first-run baseline stays as the
fallback for companies added directly via git):

1. Edit `watchlist.yaml`, commit, push.
2. Export the current ledger from Notion (step 1 of the daily run).
3. Run `fetch-edgar` — the new company has no ledger rows, so it comes back
   in baseline mode (30-day window) automatically.
4. Web-search the company's last ~30 days per its focus areas; run `dedup-web`.
5. **Skip the email.** Baseline items are never emailed, so the
   send-before-persist gate doesn't apply to them. Write the new company's
   items straight to the ledger.
6. Create its ticker page per the format below, starting the log with a
   compact baseline block.

That evening's scheduled run then sees ledger rows for the ticker, treats it
as established, and only emails genuinely new items.

## Ticker page format

Each `TICKER — Company` page has two parts:

1. **Company dossier (top):** a full research write-up. The format is fully
   specified right here — it requires **no access to any other Notion pages**.
   Open with the line
   "*Dossier maintained by the daily routine — last updated YYYY-MM-DD*",
   then these sections in order:
   - **Investing Highlights & Risks** — "Top 5 Investing Highlights" and
     "Top 5 Risks" sublists; each item is one bolded takeaway plus 1–2
     supporting sentences with specifics (numbers, dates).
   - **Overview** — one substantial paragraph: what the company does, where
     it sits in its industry, and the current situation that makes it worth
     tracking. Then a key-facts block: ticker/CIK, HQ, CEO/control, any
     situation-specific lines (IPO terms, deal structure, credit notes), and
     a **Tracking focus** line listing the entry's `focus_areas` from
     watchlist.yaml — or, if it has none, "default focus areas" plus the
     default list from CLAUDE.md.
   - **What It Actually Does** — segments/products as bullets.
   - **What Differentiates It** — the moat / structural advantages, bulleted.
   - **vs. [competitor]** — 2–3 short comparison sections against the
     names that matter.
   - **Investment Thesis** — numbered bull-case points.
   - **Financials & Metrics** — bulleted, with an explicit as-of date.
   - **Investment Risks** — the bulleted bear case.
   - **Notes & Links** — a dated timeline of key events.
   Written once at onboarding from the baseline material. Daily runs do NOT
   rewrite it — they surgically update only the lines the day's items affect
   (Financials & Metrics, the Notes & Links timeline, and the Overview
   paragraph when something genuinely material lands — deal closed, IPO
   priced, leadership change) and bump the last-updated date.
2. **Log (below):** reverse-chronological entries — date, source, headline,
   one-line summary, link. Baseline batches may be one compact block.

## Manual dry-run (local testing)

```
pip install -r requirements.txt
set SEC_USER_AGENT=Your Name you@example.com   # PowerShell: $env:SEC_USER_AGENT = "..."
python -m stock_updates fetch-edgar --watchlist watchlist.yaml --ledger examples/ledger.empty.json --out edgar_new.json
python -m stock_updates dedup-web --items examples/web_items.sample.json --ledger examples/ledger.sample.json --out web_new.json
python -m stock_updates send-email --digest examples/digest.sample.json --dry-run
```

No email is sent and nothing touches Notion. With `ledger.empty.json` every
ticker is in baseline mode; re-run `fetch-edgar` with the produced keys in the
ledger file to watch dedup drop everything (idempotency check).

## Notes & future enhancements
- The whole flow is idempotent: dedup is ledger-membership, and the ledger is
  written only after a confirmed send. A crashed run simply retries tomorrow.
- Worst case (send succeeds, ledger write fails) is a rare duplicate item the
  next day — accepted by the spec.
- **Not yet implemented (optional in spec):** EDGAR full-text search
  (`efts.sec.gov`) for focus-keyword hits, and a per-ticker `last_run` to
  widen the lookback window after gaps.
