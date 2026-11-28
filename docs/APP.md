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

A first day shows no change. A source that fails keeps its last good value and its date. A scraped price more
than 15% away from the last good one is treated as a misread page and ignored.

## The page

One file, `app/index.html`, with no libraries. Tabs: Stocks (Desk, Intraday, Swing, Long), Markets, TFeed,
Explore, and Ratings and Performance, in the order of the approved layout. The phone remembers the theme, the
tab, every ‹ › switch and the chart choices; it also keeps the last data it loaded, so the app opens offline with
a note saying which copy it shows.

A card whose data does not exist yet stays hidden (no empty boxes). Still waiting for data (B1b-2): Market this
morning, Today's read, the Intraday plan, per-trade candle charts, Council test detail, the Auto bar ladder,
Swing/Long holdings, Suggested today, News breakouts, and how many skipped trades would have lost.

A test (`tests/test_app_export.py`) checks that every dataset the page reads has a query file, and that every
market value it shows is fetched.
