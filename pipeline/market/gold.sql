-- upx-market: NSE files (bhavcopy with delivery, deals, filings, results calendar) and the copied history.
-- Runs 20:05 IST, after the NSE evening job.
-- Gold: what the dashboard, the app and the reviews read.

CREATE OR REFRESH MATERIALIZED VIEW gold.deals_board
COMMENT 'NSE bulk and block deals of ₹1 crore and more in the last 30 days, biggest first within each day.'
AS SELECT day, kind, symbol, client, side, qty, price, round(value_rs / 1e7, 2) AS value_cr
FROM silver.deals WHERE value_rs >= 1e7 AND day >= date_sub(current_date(), 30);

-- A plain view (no storage, no compute until someone opens it) across all three pipelines' tables.
CREATE VIEW gold.data_freshness
COMMENT 'The newest day each source has reached, to spot a job that stopped.'
AS SELECT 'journal' AS source, max(trade_date) AS newest_day FROM upx.silver.trade_events
UNION ALL SELECT 'pools', max(day) FROM upx.silver.pool_days
UNION ALL SELECT 'Telegram feed', to_date(max(sent_at)) FROM upx.silver.feed
UNION ALL SELECT 'shadow trades', max(day) FROM upx.silver.shadow_trades
UNION ALL SELECT 'shadow status', max(day) FROM upx.silver.shadow_status
UNION ALL SELECT 'shadow ledgers', max(day) FROM upx.silver.shadow_ledgers
UNION ALL SELECT 'NSE bhavcopy', max(day) FROM upx.silver.nse_eq_daily
UNION ALL SELECT 'NSE deals', max(day) FROM upx.silver.deals;
