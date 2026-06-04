# stock_updates

A daily, cloud-run digest of new SEC filings and news for a watchlist of
companies, delivered by email. It runs entirely as a **Claude Code Routine** on
Anthropic's cloud — no local machine, no server, no cron.

## How it works

Once a day the routine:
1. Reads your watchlist (`watchlist.yaml`) from this repo.
2. For each company, checks **SEC EDGAR first** for new filings, then searches
   the **web** for important news — guided by that company's focus areas (or a
   default set).
3. Keeps only items it hasn't already reported (deduped against a ledger in
   Notion).
4. Writes the new items to a per-company page in Notion and emails you one
   consolidated digest. On a day with nothing new, it sends a short
   "no updates today" note.

Because routines are stateless (every run starts fresh), the "don't repeat
myself" memory lives in **Notion**, not in the routine.

## Files

- `SETUP.md` — **setting this up for yourself?** Point Claude Code at that
  file and it will walk you through everything (Notion, email, the routine).
- `watchlist.yaml` — the companies you track. **This is the file you edit.**
- `CLAUDE.md` — the full build/behavior spec. Point Claude Code at this to build
  the project, and leave it in the repo so each routine run follows it.
- `RUNBOOK.md` — how each run actually executes: the exact CLI steps, the JSON
  contracts between them, and a manual dry-run recipe.
- `stock_updates/` — the Python package: rate-limited EDGAR fetching, dedup-key
  computation, and digest email building/sending (`python -m stock_updates`).
- `examples/` — sample JSON fixtures for dry-running the CLI locally.
- `requirements.txt` — Python dependencies (`requests`, `PyYAML`, `tzdata`).
- `README.md` — this file.

## One-time setup

> **Easiest path:** open this repo in Claude Code and say *"Read SETUP.md and
> walk me through setting this up."* It automates everything below that can be
> automated and includes the gotchas (env-var location, network allowlist).
> The steps here are the manual reference.

### 1. Create the repo
Create an empty GitHub repo named `stock_updates`, add these three files, and
commit. (Or hand `CLAUDE.md` to Claude Code and let it scaffold the rest.)

### 2. Edit your watchlist
Open `watchlist.yaml`, add your companies (ticker + name, optional focus areas
and CIK — the CIK matters for pre-IPO or private companies that file with the
SEC), and commit.

### 3. Set up Notion
Create one Notion page to act as the parent — e.g., "Stock Updates" — and copy
its page ID (the long ID in the page URL). On its first run the routine creates,
under that page, a ledger database and one child page per company. Connect the
**Notion** connector in Claude.

### 4. Set up email delivery
The reliable way to *send* email from a headless cloud routine is a transactional
email service (e.g., Resend, SendGrid, Postmark — all have free tiers). Create an
account, verify a sender address, and get an API key. (See the delivery note in
`CLAUDE.md`: the Gmail connector is an alternative but in routines may only create
a draft rather than send.)

### 5. Set environment variables
Environment variables live on the **cloud environment** the routine runs in,
not on the routine itself: open the routine at `claude.ai/code/routines`, click
the pencil (Edit routine), select the environment shown below the Instructions
box, click its settings icon, and add the variables in the **Environment
variables** section (`KEY=value`, one per line, no quotes). Note there is no
separate secrets store yet — values are visible to anyone who can edit that
environment. Add:

| Variable | Example | Purpose |
|---|---|---|
| `SEC_USER_AGENT` | `Jane Doe jane@example.com` | Required by SEC EDGAR (name + email). |
| `RECIPIENT_EMAIL` | `you@example.com` | Where the digest is sent. |
| `SENDER_EMAIL` | `updates@yourdomain.com` | Verified "from" address for the email service. |
| `EMAIL_API_KEY` | `re_xxx` | API key for your email service. |
| `NOTION_PARENT_PAGE_ID` | `2b1f…` | The "Stock Updates" parent page. |
| `TIMEZONE` | `America/New_York` | For digest dates / lookback windows. |

Secrets go in the routine's Environment Variables, never in the repo.

### 6. Create the routine
At `claude.ai/code/routines` (or `/schedule` in the Claude Code CLI): create a
routine, **attach this repo**, **attach the connectors** (Notion, web search /
Exa, and Gmail if you use it), set the prompt below, and set a **daily schedule**
(e.g., 7:00 AM — runs may start a few minutes late). Optionally add an **API
trigger** so you can also run it on demand.

Suggested routine prompt:

> This is a scheduled daily run of stock_updates. Follow RUNBOOK.md in this
> repository step by step — it is the per-run orchestration contract
> (CLAUDE.md is the behavior spec it implements). Read the Notion ledger, run
> the fetch-edgar CLI, search the web per company, run dedup-web, write your
> own 1–2 line summaries, send with the send-email CLI, and ONLY after a
> successful send write the new items to Notion and update the per-ticker
> pages. Configuration comes from the environment variables. Never commit or
> push to the repository.

### 7. Dry run first
Trigger the routine manually once and check the session logs at `claude.ai/code`,
the Notion pages, and the email before trusting the schedule.

## Updating the watchlist & focus areas
Make all changes through Claude Code — no hand-editing required. Open the **Code**
tab in the Claude mobile app (or `claude.ai/code` in a browser), select the
`stock_updates` repo, and describe the change in plain language. For example:

- "Add a company to `watchlist.yaml`: Crown Castle, ticker CCI."
- "Set EchoStar's focus areas to spectrum monetization, the Boost/5G buildout, FCC
  buildout milestones, and debt/refinancing."
- "Remove EchoStar's `focus_areas` so it falls back to the defaults again."
- "Drop CCI from the watchlist."

Claude Code edits `watchlist.yaml`, commits it, and — per `RUNBOOK.md`'s
onboarding flow — immediately records the new company's 30-day baseline in
Notion and creates its research page, all in the same session. The next
scheduled run treats the company as established and emails only genuinely new
items; your first email about it is never a giant backlog. (Companies added by
editing the YAML directly instead get their baseline automatically on the next
scheduled run.)

(You can also edit `watchlist.yaml` directly in GitHub if you ever prefer, but
routing changes through Claude Code means you just describe what you want.)

## Good to know
- **Research preview:** Claude Code Routines are a research preview; behavior and
  limits can change. A failed run does **not** auto-retry — it just appears in
  your session list. Consider a periodic check or the optional weekly heartbeat
  in `CLAUDE.md`.
- **Cost:** each run uses your Claude subscription's usage (by tokens) and counts
  against your plan's daily routine cap; usage grows with the number of companies
  and the research depth.
- **SEC fair access:** EDGAR is free and key-less but requires the
  `SEC_USER_AGENT` header and a max of 10 requests/second — the script paces
  itself accordingly.
