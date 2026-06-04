"""stock_updates — daily SEC filings + news digest tooling.

This package is the deterministic half of the project: EDGAR fetching,
dedup-key computation, and email building/sending. The Notion ledger and web
search are handled by the Claude Code Routine via connectors, orchestrated as
described in RUNBOOK.md.
"""

__version__ = "0.1.0"
