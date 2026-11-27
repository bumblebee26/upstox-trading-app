# Rebuild plan: one repo on Upstox (approved 26 Nov 2026)

Dummy money only. Nothing here is investment advice. The old system is described in `REBUILD_SPEC.md` (Claude project "Upstox Trader"); this file records
what changes and in what order.

## 1. Approach

A fresh rebuild, written from the spec. The old repos (`paper-trader`, `stocks_lakehouse`) are reference only.

1. The old system keeps trading, frozen (no new features), until switch-over.
2. The old tests that pin money rules (risk gate, sizing, costs, loss limits, reconciliation) are rewritten
   as this repo's acceptance tests before the code they cover.
3. Parallel run for 3 sessions after the fresh start (section 6): the new system trades on the second Telegram
   bot with its own ledger; each evening a report compares proposals, fills, P&L and reconciliation.
4. Switch-over on the weekend after the parallel run. Then the old repos are archived and their resources removed.

## 2. Isolation from the old repos (owner's rule)

Removing everything the old repos created must not touch anything this repo uses.

| Resource | Old repos | This repo |
|---|---|---|
| Name prefix | `stocks-`, `stocks-trader-` | `upx-` |
| Terraform state | `stocks-lakehouse-tfstate-<account>` | own bucket `upx-tfstate-<account>`, created by `infra/bootstrap` |
| S3 buckets | landing, trader state, desk app | `upx-landing-<account>`, `upx-state-<account>`, `upx-app-<account>` |
| SSM parameters | `/stocks/*`, `/stocks-trader/*` (several are owned by old Terraform and would be deleted with it) | `/upx/*` only. Secret values are entered by the owner and never stored in Terraform state |
| IAM users and roles | `stocks-gha-*`, `stocks-*-role` | `upx-gha-*`, `upx-*-role` |
| Lambdas, schedules, log groups | `stocks-*` | `upx-*` |
| Databricks | catalog `stocks` (managed volumes: dropping it deletes the files), its jobs, pipelines, dashboard, warehouse token | catalog `upx`, own volumes, pipeline, jobs, dashboard and service token |
| Telegram | main bot | second bot during the parallel run; the main bot's token is copied to `/upx/telegram-bot-token` at switch-over |

Rules:
- Nothing in this repo reads a `stocks-` bucket or a `/stocks/` parameter at run time. A CI check fails on any
  `stocks-` or `/stocks/` reference outside `docs/` and the one-time copy job.
- Data from the old system comes across once, by copy (never by reference): the history files of the old
  Databricks landing volume (section 3, "History kept"). The copy finishes and is checked (file counts and bytes)
  before anything old is removed.
- Before removing the old stacks: run `terraform plan -destroy` on each and confirm that no `upx-` resource appears.
- The two parameters the owner already created (`/stocks/upstox-analytics-token`, `/stocks/telegram-bot-token-v2`)
  were made by hand, so old Terraform cannot delete them. They are copied to `/upx/upstox-analytics-token` and
  `/upx/telegram-bot-token-v2`; the `/stocks/` copies are deleted at clean-up.

## 3. What the system does after the rebuild

**Data.** Upstox for Indian prices (quotes, 1/5/15-minute and daily candles), calendar, instrument list,
fundamentals, corporate actions, news, FII/DII flows, charges check and market depth. Kept from other sources:
NSE bhavcopy + delivery, NSE pre-open, NSE filings, NSE bulk and block deals (new), Nifty 200 list, Massive (US),
FRED, Yahoo (world tiles only), IBJA, CarDekho, RBI, SEBI, Business Standard.

**Real pools: AI decides, code guards the money.** All three start in auto mode on a fresh ledger
(₹40,000 / ₹60,000 / ₹1,00,000).
- Code builds a facts packet per stock (candles at several timeframes, every indicator and pattern in the
  catalog, levels, volume, sector and index, news and filings, flows, costs, the pool's own track record).
- Claude decides buy, sell, hold, add, trim or exit, and sets the stop and target. An independent reviewer argues
  against each decision; its score is logged, the AI makes the call.
- Objectives: intraday, the highest net P&L for the day after costs, flat by 15:10; swing and long-term, the
  highest profit per position over its hold.
- When the AI decides: intraday every 5-minute candle; swing daily after the close and at once on news about a
  holding; long-term every Saturday and on results or news.
- Hard limits in code: risk per trade 1% (VIX-scaled), 4R daily loss limit, 8R weekly brake, 12% circuit breaker,
  position, margin and sector caps, entry window, 15:10 square-off. Quantity comes from the AI's stop so the ₹ risk
  is fixed. The AI may tighten, trail or exit; it may never widen a stop. Code fires the stop: intraday checked every
  minute, swing and long-term at each close. Long-term also has a −25% floor if the AI's stop is not tighter.
- Every decision is saved with its facts packet so it can be replayed.

**History kept (owner, 27 Nov): files, never tables.** The old landing volume's NSE (bhavcopy, delivery,
indices, F&O list), fundamentals, index members, US (Massive) and FRED files are copied once to
`/Volumes/upx/bronze/history/` and loaded by the new pipelines, so backtests can use years of data. The old trader
journals, pools and Yahoo data are not copied.

**Shadows (paper, rule-based, no Claude calls).** About 60 intraday, 25 swing and 18 long-term strategies, listed in
`docs/STRATEGIES.md` before any are built; regime overlays (VIX band, breadth, Nifty vs 200-day average);
AI-versus-rules split tests built from the AI's saved decisions; NIFTYBEES buy-and-hold and monthly SIP as
benchmarks for swing and long-term. The real pools never hold NIFTYBEES as parking.

**Telegram.** Same commands, YES/NO, 👍/👎 reactions, EXIT and ℹ️ Full reasons. No `[MOCK]` prefix (the bot's name
and description say paper trading). Short brief and proposals; detail behind ℹ️ Full reasons.

**App** stays the main screen: adds a Feed tab (every Telegram message, read-only) and a per-trade candle chart
(entry, stop, target, exit; also for passed trades).

**Databricks dashboard** mirrors the app: every dataset the app shows comes from one view that both read; pages
Desk, Intraday, Swing, Long-term, Markets, Feed, Your calls; a CI check fails if the app reads a dataset the
dashboard lacks. Three PySpark pipelines, each run only at its own time and only when its files are new:
`upx-trading` (13:05, 16:55), `upx-shadows` (17:30), `upx-market` (20:05); `ai_summarize` once a day.

## 4. Limits

- **Upstox** (per API, per user): 50/s, 500/min, 2,000 per 30 min. One limiter in `core/upstox.py` paces every
  caller, backs off on 429 and logs a daily count per API. Planned use stays under 10% of each limit in market
  hours; backfills and fundamentals run outside market hours.
- **AWS free plan:** only S3, Lambda, EventBridge Scheduler, SSM, IAM and CloudWatch Logs. The owner checks the
  plan's end date and credits in Billing.
- **Databricks Free Edition:** one pipeline at a time and a daily compute quota; during the parallel run only the
  old lakehouse runs; the dashboard queries only when opened.
- **GitHub:** public repo (free minutes, rulesets); scheduled workflows can run hours late, so time-critical runs
  start from the AWS kicker.

## 5. Build order (stacked pull requests)

| # | Pull request |
|---|---|
| 1 | Foundation: CLAUDE.md, docs, CI, isolation check, `core/http.py` and `core/ssm.py` with tests |
| 2 | `core/upstox.py`: client, limiter, instrument map, quotes, candles, calendar, charges, news, fundamentals |
| 3 | Money core: ledger, costs, sizing, risk gate, journal (acceptance tests first) |
| 4 | Facts packet: indicators, candle and chart patterns, levels, market context |
| 5 | Intraday AI trader: MCP tools, playbook, reviewer, session workflow, short Telegram messages, feed copy |
| 6 | Swing and long-term AI pools |
| 7 | `docs/STRATEGIES.md`, then the shadow engine with the intraday catalog |
| 8 | Swing and long-term shadows, benchmarks, families and luck lines |
| 9 | AWS: bootstrap, Lambdas (kicker, guardian, responder, fetchers, brief), schedules, IAM |
| 10 | Lakehouse: catalog `upx`, one pipeline, one-time copy of old data and learning |
| 11 | App (Feed tab, trade chart) and the matching dashboard |
| 12 | Parallel-run report, minute-history backfill, switch-over and clean-up runbook |

Each pull request: plan, the owner says "go", tests first, code review, the owner says "merge".
UI changes come with light and dark screenshots.

## 6. Status and order of work (owner, 27 Nov 2026)

The first live day (27 Nov) showed problems, so **trading is off until go-live**: every scheduled job and the
five job workflows are paused (`local.paused` in `infra/aws/kicker.tf`); only the Telegram responder runs.
Everything is built and tested first; then the system starts fresh.

**Stage 1: fixes (from 27 Nov)**
| # | Fix |
|---|---|
| F1 | Indicator warm-up: the previous day's 1-minute candles, so the 5m and 15m indicators are ready at 09:15 (on 27 Nov the AI had none until about 10:15) |
| F2 | FII/DII flows: Upstox sends ₹ crore, newest first; the brief and the AI's `start_day` read them wrongly (₹0 cr, and the oldest day) |
| F3 | History: the copy workflow follows a running job; the inventory is read; history tables in `upx-market` |
| F4 | Review of the 27 Nov sessions: anything else in the facts, tools or playbook that held the AI back |

**Stage 2: finish building**
| # | Build |
|---|---|
| B1 | App and dashboard (PR 11): Feed tab, per-trade chart, matching Databricks dashboard; light and dark screenshots |
| B2 | Minute-history backfill (2022–26) and backtests of every intraday rule (train 2022–24, check 2025–26) |
| B3 | Go-live tooling: a fresh-start script (new ledgers, test state archived) and the parallel-run report |

**Stage 3: test everything (nothing may break)**
| # | Test | Proves |
|---|---|---|
| T1 | Unit tests and CI on every pull request | each piece works |
| T2 | Rehearsal day: a real past day replayed minute by minute through the intraday engine (stops, square-off, guardian) into a test folder, Telegram captured to a log | the day runs end to end, no Claude usage |
| T3 | One real AI rehearsal on the replayed day | the AI gets usable facts from 09:15 and can propose |
| T4 | Dry run of every job (pools, shadows, NSE, brief, lakehouse, guardian, responder) on real data into the test folder | every job works with the live APIs |
| T5 | The three lakehouse pipelines on the test data | tables load |
| T6 | `terraform plan` shows no changes; Checkov and the isolation check pass | AWS and Databricks match the code |

**Stage 4: fresh start (proposed Mon 7 Dec, owner to confirm)**
1. The fresh-start script resets every pool and shadow ledger; NSE and history data are kept.
2. `local.paused = false`, apply, and turn the five workflows back on.
3. Parallel run with the old system for 3 sessions, then the switch-over.
