# CLAUDE.md — build & behavior spec for `stock_updates`

This file is the source of truth for what `stock_updates` does. Implement the
project to match it, and follow it on every scheduled run. Treat it like
onboarding instructions for a new hire: explicit steps, defined outputs, clear
rules for edge cases.

## What this is
A Python project that runs as a **Claude Code Routine** (cloud, scheduled
daily). On each run it gathers *new* SEC filings and news for a watchlist of
companies, records them in Notion, and emails one consolidated digest.

## Runtime model — read this first
- **Stateless.** Every run is a fresh container with a fresh clone of this repo
  and no memory of previous runs. All cross-run memory MUST be read from / written
  to Notion.
- **No local files or secrets.** Configuration secrets come from environment
  variables set on the routine (listed below). Do not read local `.env` files,
  and never commit secrets.
- **Do not write to the repo.** Don't commit, don't push branches. The repo is
  read-only input.
- **Connectors available:** Notion (read/write), web search (and/or Exa), and
  optionally Gmail. Use them via their tools.
- **Sourcing / copyright:** summarize in your own words and link to the source.
  Never paste full article text or full filing text into Notion or the email.

## Inputs

### `watchlist.yaml` (in repo)
A top-level `companies:` list. Each entry:
- `ticker` — string, required (may be `null` for a private company with no SEC
  presence).
- `company` — string, required.
- `cik` — integer, optional. Explicit SEC CIK; takes precedence over
  ticker-map resolution. Use for pre-IPO tickers not yet in the SEC ticker map
  or private companies that still file (Form D etc.).
- `focus_areas` — list of strings, optional.

### Environment variables (from routine settings)
- `SEC_USER_AGENT` — name + email; send it as the `User-Agent` header on every
  SEC request.
- `RECIPIENT_EMAIL` — digest recipient.
- `SENDER_EMAIL` — verified "from" address for the email service.
- `EMAIL_API_KEY` — transactional email API key (see Delivery).
- `NOTION_PARENT_PAGE_ID` — parent page under which to create/maintain everything.
- `TIMEZONE` — IANA tz (default `America/New_York`).

## Persistent store (Notion)
On first run, under `NOTION_PARENT_PAGE_ID`, create if missing:

1. A **ledger database** ("stock_updates ledger") with properties:
   - `key` (title) — the unique dedup key (see Dedup).
   - `ticker` (text)
   - `source` (select: `edgar` | `web`)
   - `item_type` (text) — e.g. a form type ("8-K") or "news".
   - `headline` (text)
   - `url` (url)
   - `event_date` (date) — filing date or article date.
   - `first_seen` (date) — when this run recorded it.
2. One **child page per ticker** (titled `TICKER — Company`) with a full
   **company dossier** at the top (research write-up in the house format —
   highlights/risks, overview, segments, competitors, thesis, financials, key
   questions; see RUNBOOK.md "Ticker page format"), followed by a
   reverse-chronological, human-readable log of what was reported (date, source,
   headline, one-line summary, link). The dossier is written at onboarding;
   daily runs surgically update the parts the day's news affects.

Read the ledger at the start of each run; write new rows at the end (see ordering
under Email + persist).

## Default focus areas
Used for any company without its own `focus_areas`:
- **Material 8-K events:** M&A, executive/board changes, guidance changes,
  restructuring, material agreements, delisting/bankruptcy.
- **Earnings & guidance:** results, pre-announcements, revisions.
- **Capital structure & financing:** equity/debt offerings, buybacks, dividends,
  large debt actions.
- **Insider & institutional activity:** Form 4 insider transactions; 13D/13G
  stake changes.
- **Legal & regulatory:** litigation, investigations, regulatory actions/approvals.
- **Major business news:** large customer/partnership/product/contract
  developments; analyst rating changes (web).

## Run logic (daily)
Handle each company independently — one company's failure must not abort the run.

1. **Resolve CIK.** An explicit `cik` in the watchlist wins. Otherwise, if
   `ticker` is set, map ticker → CIK using
   `https://www.sec.gov/files/company_tickers.json` (cache for the run). If there
   is no CIK by either route, skip EDGAR for this company, do web-only, and
   note it.

2. **EDGAR first.** GET
   `https://data.sec.gov/submissions/CIK{cik_zero_padded_to_10}.json` with the
   `SEC_USER_AGENT` header. From `filings.recent`, take filings within the
   lookback window (default 7 days; see First-run baseline) whose accession number
   is not already in the ledger. Prioritize material forms: 8-K, 10-K, 10-Q, S-1,
   S-3, S-4, 424B*, SC 13D, SC 13G, 3/4/5, DEF 14A, 6-K, 20-F, and — for
   private/pre-IPO filers — D, DRS, FWP, 8-A12B/G. For each new material
   filing, fetch it and extract the parts relevant to the focus areas (e.g., the
   8-K item, key changes). Optionally use EDGAR full-text search (efts.sec.gov;
   covers filings since 2001 — verify the current endpoint in SEC docs) for
   focus-keyword hits. Respect SEC limits: ≤10 requests/second, ~100 ms between
   requests, back off on HTTP 429.

3. **Then web.** Search for important recent news (within the lookback window)
   about the company and its focus areas, using web search and/or the Exa
   connector. Prefer primary and reputable sources.

4. **Dedup → keep only new.** Drop any item whose dedup key is already in the
   ledger. (See Dedup.)

5. **Summarize.** For the new items, write concise, sourced bullets in your own
   words, grouped by company and then by source (EDGAR before web), each tied to a
   focus area where relevant, with a link.

After all companies are processed:

6. **Email + persist (in this exact order):**
   - Build one consolidated digest (see Output).
   - Send the email (see Delivery).
   - **Only after a successful send,** write the new items to the Notion ledger
     and append summaries to each ticker's page.
   - Rationale: if the email fails, the items stay un-ledgered and are retried on
     the next run (no silent loss). The worst case is a rare duplicate if the send
     succeeds but the ledger write fails — acceptable.

## Dedup
- **Key (EDGAR):** the filing accession number (globally unique).
- **Key (web):** normalize the URL (lowercase host, strip `utm_*`/tracking params,
  drop fragments), then `sha1(normalized_url)`. To catch the same event from a
  second source, also compare `sha1(lower(headline) + source)`.
- **Lookback window:** default 7 days, to bound searches and survive skipped runs.
  Primary dedup is ledger membership, not exact timing.
- Optionally store/read a per-ticker `last_run` to widen the window after a gap.

## First-run baseline (per ticker)
When a ticker has **no** existing ledger rows (first time tracked, or just added):
record its recent filings/news from the last ~30 days into the ledger as "seen"
**without emailing them**, and include only a one-line "Now tracking TICKER" in
that day's digest. This prevents a huge first-day backlog; only genuinely new
items are emailed thereafter.

Preferred: when a company is added through an interactive Claude Code session,
run its baseline immediately at add-time (see RUNBOOK.md "Onboarding"). No
email is involved, and baseline items are exempt from the send-before-persist
rule since they are never emailed. The scheduled run's automatic baseline
remains the fallback for companies added directly via git.

## Delivery (email)
Send via a transactional email API (e.g., Resend) using `EMAIL_API_KEY`, from
`SENDER_EMAIL` to `RECIPIENT_EMAIL`.
- Recommended: a single POST to the provider's send endpoint with an HTML (or
  markdown-converted) body.
- Alternative: the Gmail connector — but in a routine it may only create a
  *draft* rather than send. If you use it, confirm it can actually send; if it can
  only draft, use the email API instead.
- Subject (same format every day, including no-news days):
  `Stock Tracker Daily Update: {Month D, YYYY}`
  (e.g., `Stock Tracker Daily Update: June 4, 2026`). The body header carries
  the counts; a quiet day reads "No updates today." in the body.

## Output (email body)
- Short header line (date, totals).
- For each company with new items: a `TICKER — Company` subhead, then EDGAR items,
  then web items, each a one- or two-line summary with a source link. Tag the
  focus area when relevant.
- Companies with nothing new are omitted from the body (but counted in the header).
- If nothing is new across the whole watchlist: a brief "No updates today." line
  plus the list of tickers being tracked. (User preference: always send this note.)
- Skipped/failed companies: a short "Couldn't check X today (reason)" line so
  failures aren't silent.

## Error handling
- Wrap each company in try/except; on error, record it for the digest and continue.
- Handle: missing CIK, SEC 403 (usually a missing/incomplete User-Agent), SEC 429
  (back off and retry within the run), and web-search failures.
- If the run can't even start (e.g., Notion unreachable), fail loudly in the
  session logs.

## Optional: weekly heartbeat
Because failed runs don't auto-retry or notify, optionally include — once a week —
a one-line "routine healthy — last N runs OK" footer, so a *missing* email becomes
a signal that something broke.

## Implementation notes
- Python; keep dependencies minimal (`requests`, `PyYAML`; standard library
  otherwise).
- Make it idempotent and safe to re-run manually for testing.
- Log clearly to stdout (counts per company, what was sent, what was skipped) — the
  routine's session logs are the main debugging surface.

## Implementation map
This spec is implemented as the `stock_updates/` Python package (EDGAR fetch,
dedup keys, email build/send) plus `RUNBOOK.md`, the per-run orchestration
contract. **On a scheduled run, follow `RUNBOOK.md` step by step** — it says
which commands to run and how to use the Notion and web-search connectors
around them.
