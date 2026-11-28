# The phone app

The approved layout is on the design canvas and in the project doc `claude/APP_LAYOUT.md`. This page says where
the app's pieces live and how its data gets there.

## Opening the app

The app has a secret address. The owner keeps it in Parameter Store at `/upx/app-url` (added by hand, outside
Terraform). It can also be read on the PC:

```
cd infra/aws
terraform init
terraform output -raw app_url
```

Anyone with the link can open the app (it shows paper money only). Only that path is served; any other address
shows "Not found".

## How it works

| Piece | Where | What it does |
|---|---|---|
| The page | `app/index.html` (one file: page, styles, script) | Uploaded to the `upx-app` bucket by Terraform on each apply |
| The server | `lambdas/app_web.py`, `infra/aws/app.tf` | A Lambda function URL serves `/<secret>/<file>` from the bucket |
| The data | `appdata/export.py` | The last step of the Lakehouse job, after the pipelines |
| Datasets | `appdata/queries/*.sql` | One file per dataset; the dashboard (B1c) reads the same files |

Each export writes:

- `app/data/desk.json`: every dataset's rows, the market values with their day change, and a list of anything
  that failed. A dataset that fails keeps its previous rows.
- `app/data/stocks.json`: every NSE stock (symbol, name, industry, indices, F&O lot, Upstox link), rebuilt once a
  day. Index lists come from NSE's index files and refresh once a month.
- `history/markets/`: the market values book (today and the previous saved day) and a copy for each day.

## Market values

| Item | Source | Change shown |
|---|---|---|
| Nifty 50, Sensex, India VIX | Upstox quotes | From the previous saved day |
| Gold 999, silver 999 | IBJA (closing PM rate of the latest day) | From the previous saved day |
| USD/INR | Coinbase (live, indicative); MoneyConvert if Coinbase fails | From the previous saved day |
| Mumbai petrol, diesel, CNG | Upstox's Mumbai fuel pages | From the previous saved day |
| Accenture (NYSE: ACN) | Massive, the last US close (key in `/upx/massive-api-key`) | From the previous saved day |

**World vs India chart (Markets):** five years of daily closes for Nifty 50, Sensex, S&P 500, Nasdaq 100,
Nikkei 225, Hang Seng and FTSE 100, all from Upstox (world indices use Upstox's `GLOBAL_INDEX` keys, served to
the read-only Analytics token). Fetched fresh on every export, so nothing is stored. Each line shows its % change
from the first day in view; the line under the chart compares Nifty 50 with the average of the five world
indices. If every index fails, the last good copy stays.

A first day shows no change. A source that fails keeps its last good value and its date. A scraped price more
than 15% away from the last good one is treated as a misread page and ignored.

## The page

One file, `app/index.html`, with no libraries. Tabs: Stocks (Desk, Intraday, Swing, Long), Markets, TFeed,
Explore, and Ratings and Performance, in the order of the approved layout. The phone remembers the theme, the
tab, every ‹ › switch and the chart choices; it also keeps the last data it loaded, so the app opens offline with
a note saying which copy it shows.

Every chart shows its value range on the left and dates below. Moving a finger or the mouse over a chart (or
tapping it) draws a guide line with a dot on each line, the date on top, and every value at that day under the
chart, highest first.

The app is called Paper Trader. It opens on a green screen with the icon and name for at least 2 seconds,
then fades once the first page is drawn.

A card whose data does not exist yet stays hidden (no empty boxes). Where the cards get their data:

| Card | From |
|---|---|
| Market this morning | The latest brief message in the Telegram feed |
| Today's read | One line worked out from the day's NSE prices (breadth, best and worst sector) |
| Intraday plan, Auto bar and sizing | The code limits (`trader/risk.py`) and auto mode, read from the trader's saved state; the 09:25 screen list from the journal |
| Per-trade candle charts | The export fetches each reviewed stock's 5-minute candles for that day from Upstox |
| Skipped ideas | The same candles: whether the stop or the target came first after the review |
| Council test | Each review's council and AI YES % against the trade's result (`council.sql`) |
| Holdings now | The pools' saved state, with today's close |
| Suggested | The pool's last decision: its ranked candidates and chosen buys |
| News breakouts | Stocks with an NSE filing that rose 3% or more |

The Auto bar card shows today's limits only: there is no record of past limit changes yet (a "ladder" of versions
needs each change logged, which can start at a review).

A test (`tests/test_app_export.py`) checks that every dataset the page reads has a query file, and that every
market value it shows is fetched.
