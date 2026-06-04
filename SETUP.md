# SETUP.md — set up your own stock_updates

> **If you are Claude Code reading this:** your job is to walk your user
> through this setup interactively. Do every step you can yourself — creating
> the Notion parent page via the connector, creating the routine, verifying
> EDGAR access, dry-running the email — and hand the user only the steps that
> genuinely require a human (account signups, pasting secrets, connecting
> connectors). Read `CLAUDE.md` (the behavior spec) and `RUNBOOK.md` (the
> per-run orchestration) before you start. Never ask the user to paste a
> secret into the chat; secrets go directly into the environment settings UI.

## What this is

A daily Claude Code Routine that checks **SEC EDGAR first, then the web** for
each company in `watchlist.yaml`, dedups against a ledger kept in **Notion**,
and emails **one consolidated digest** (or a short "no updates" note). A newly
added company gets a silent 30-day baseline so the first email is never a
backlog dump. Stateless by design — all memory lives in Notion.

## What you need (and what you don't)

| Needed | Why |
|---|---|
| Claude subscription with **Claude Code Routines** | runs the daily job in the cloud |
| **GitHub** account | hosts your own copy of this repo |
| **Notion** (free tier fine) + the Notion **connector** | the cross-run memory (ledger + per-ticker pages) |
| **Resend** account (free tier: 100 emails/day; this sends 1) | actually delivers the email |
| Web search — built-in or the **Exa** connector | the news half of each run |

**You do NOT need Google/Gmail.** The Gmail connector cannot send email from a
routine — it can only create drafts — which is exactly why delivery goes
through a transactional email API instead.

## Step 1 — Make your own copy of the repo *(Claude can do this)*

Don't attach your routine to someone else's repo: the watchlist is personal
and the routine reads it fresh every run. Create your own copy (GitHub
**Import repository**, or clone + push to a new private repo), then edit
`watchlist.yaml` to your companies. Fields per entry: `ticker` (or `null`),
`company`, optional `cik` (for pre-IPO/private SEC filers), optional
`focus_areas`.

## Step 2 — Notion *(human: 1 click; Claude: the rest)*

1. **Human:** connect the Notion connector at
   [claude.ai/settings/connectors](https://claude.ai/settings/connectors).
2. **Claude:** create a parent page (e.g. "Stock Updates") anywhere in the
   workspace and note its page ID — that becomes `NOTION_PARENT_PAGE_ID`.
   The routine builds the ledger database and per-ticker pages under it on
   first run; nothing else to set up.

## Step 3 — Email via Resend *(human, ~3 minutes)*

1. Sign up at [resend.com](https://resend.com) **using the address you want
   the digest delivered to** — in free "sandbox" mode Resend only delivers to
   your own signup address (a built-in allowlist of one; verify a custom
   domain later if you ever want other recipients).
2. Dashboard → **API Keys** → create one ("stock_updates", sending access).
   It's shown once — keep the tab open until step 5.
3. Your `SENDER_EMAIL` is `onboarding@resend.dev` unless you verified a domain.

## Step 4 — Create the routine *(Claude can do this)*

At claude.ai/code/routines (or have Claude use its scheduling tools): create a
**daily** routine, attach **your repo**, the **Notion** connector, and **web
search / Exa**. Note the cron schedule is in UTC. Suggested prompt:

> This is a scheduled daily run of stock_updates. Follow RUNBOOK.md in this
> repository step by step — it is the per-run orchestration contract
> (CLAUDE.md is the behavior spec it implements). Read the Notion ledger,
> run the fetch-edgar CLI, search the web per company, run dedup-web, write
> your own 1–2 line summaries, send with the send-email CLI, and ONLY after a
> successful send write the new items to Notion and update the per-ticker
> pages. Configuration comes from the environment variables. Never commit or
> push to the repository. Log per-company counts as you go.

## Step 5 — Environment variables *(human — the UI path is non-obvious)*

Variables live on the **cloud environment**, not on the routine itself:
open the routine → **pencil icon** (Edit) → click the **environment selector**
below the Instructions box → hover the environment → **settings icon** →
**Environment variables**. Format is `KEY=value`, one per line, **no quotes**:

```
SEC_USER_AGENT=Your Name you@example.com
RECIPIENT_EMAIL=you@example.com
SENDER_EMAIL=onboarding@resend.dev
EMAIL_API_KEY=re_your_key_here
NOTION_PARENT_PAGE_ID=<the page ID from step 2>
TIMEZONE=America/New_York
```

Caveats: there is no separate secrets store — anyone who can edit the
environment can read these. Environments are shared across all routines that
use them; give this routine its own environment if you run others.

## Step 6 — Network allowlist *(human — this WILL bite you otherwise)*

The default cloud environment's "Trusted" network policy **blocks
`api.resend.com`** — the first run will do everything perfectly and then fail
at the send (by design it then writes nothing to Notion and retries next
run). In the same environment-settings dialog as step 5, find **Network
access** and add:

```
api.resend.com
```

SEC's endpoints were allowed by default in our setup, but if EDGAR calls ever
fail with network errors, also add `www.sec.gov`, `data.sec.gov`, `efts.sec.gov`.

## Step 7 — First run

Trigger the routine manually and watch the session log. Expect:

- Notion: a **stock_updates ledger** database + one `TICKER — Company` page
  per watchlist entry appear under your parent page.
- Every ticker gets its **30-day baseline**: recent filings/news recorded as
  "seen" **without being emailed**.
- Inbox: a short digest ("now tracking …"). Check spam the first time —
  `onboarding@resend.dev` is a new sender.

From then on, daily runs email only genuinely new items.

## Day-2 operations

- **Add a company:** tell Claude Code ("add NVIDIA, ticker NVDA") — per
  `RUNBOOK.md` it edits the watchlist, commits, *and* onboards the company in
  the same session (baseline recorded, ticker page created) so the nightly
  run never sends a backlog.
- **Dry-run locally:** see "Manual dry-run" in `RUNBOOK.md`.
- **Failures don't retry or notify.** A missing daily email *is* the alert —
  check the session logs at claude.ai/code. The Monday digest carries an
  optional "routine healthy" heartbeat line.

## Costs

SEC EDGAR is free (it just requires the `SEC_USER_AGENT` header and ≤10
requests/sec — the code paces itself). Resend and Notion free tiers are
plenty. Each routine run consumes Claude plan usage, scaling with watchlist
size.
