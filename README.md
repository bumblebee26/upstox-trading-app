# upstox-trading-app

A paper-trading platform for NSE stocks: dummy money only, no broker link, nothing here is investment advice.

It learns, with three paper pools (intraday ₹40,000, swing ₹60,000, long-term ₹1,00,000), whether any way of
trading makes money after all costs. An AI trader runs each real pool inside hard limits held in code; dozens of
rule-based shadow strategies and a NIFTYBEES benchmark run beside it for comparison. Prices come from the Upstox
API (read-only Analytics token). Reports and approvals go to Telegram; a phone web app and a Databricks dashboard
show the results.

It replaces the earlier `paper-trader` and `stocks_lakehouse` repos and shares no resources with them.

- Plan and build order: [docs/REBUILD_PLAN.md](docs/REBUILD_PLAN.md)
- Working rules for Claude: [CLAUDE.md](CLAUDE.md)
