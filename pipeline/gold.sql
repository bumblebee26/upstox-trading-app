-- Gold: what the dashboard, the app and the reviews read. Dummy money; results are paper results, not advice.

CREATE OR REFRESH MATERIALIZED VIEW gold.trading_daily
COMMENT 'Each real pool per day: trades, wins, net after charges, end balance, and whether the balance moved by exactly the day net.'
AS WITH t AS (
  SELECT trade_date AS day, pool, count(*) AS trades, sum(CASE WHEN won THEN 1 ELSE 0 END) AS wins,
         round(sum(net_rs), 2) AS net_rs, round(sum(charges_rs), 2) AS charges_rs
  FROM silver.trades GROUP BY 1, 2
), b AS (
  SELECT day, pool, balance, lag(balance) OVER (PARTITION BY pool ORDER BY day) AS prev_balance FROM silver.pool_days
)
SELECT coalesce(t.day, b.day) AS day, coalesce(t.pool, b.pool) AS pool, coalesce(t.trades, 0) AS trades,
       coalesce(t.wins, 0) AS wins, coalesce(t.net_rs, 0) AS net_rs, coalesce(t.charges_rs, 0) AS charges_rs,
       b.balance,
       CASE WHEN b.prev_balance IS NULL OR b.balance IS NULL THEN NULL
            ELSE abs(b.balance - b.prev_balance - coalesce(t.net_rs, 0)) < 1 END AS reconciled
FROM t FULL OUTER JOIN b ON t.day = b.day AND t.pool = b.pool;

CREATE OR REFRESH MATERIALIZED VIEW gold.track_record
COMMENT 'Last 90 days by pool and setup: trades, win rate and average net (the base rate the reviewers use).'
AS SELECT pool, setup, count(*) AS trades, round(avg(CASE WHEN won THEN 1.0 ELSE 0.0 END) * 100, 1) AS win_pct,
          round(sum(net_rs), 2) AS net_rs, round(avg(net_rs), 2) AS avg_net_rs
FROM silver.trades WHERE trade_date >= date_sub(current_date(), 90)
GROUP BY 1, 2;

CREATE OR REFRESH MATERIALIZED VIEW gold.trading_by_setup
COMMENT 'All-time by pool and setup.'
AS SELECT pool, setup, count(*) AS trades, round(avg(CASE WHEN won THEN 1.0 ELSE 0.0 END) * 100, 1) AS win_pct,
          round(sum(net_rs), 2) AS net_rs, min(trade_date) AS first_day, max(trade_date) AS last_day
FROM silver.trades GROUP BY 1, 2;

CREATE OR REFRESH MATERIALIZED VIEW gold.your_calls
COMMENT 'The owner ratings against what each trade did: how often a 👍 or a 👎 was right.'
AS SELECT pool, coalesce(rating, 'unrated') AS rating, count(*) AS trades,
          sum(CASE WHEN won THEN 1 ELSE 0 END) AS won, round(sum(net_rs), 2) AS net_rs,
          round(avg(CASE WHEN rating IS NULL THEN NULL WHEN (rating = 'up') = won THEN 1.0 ELSE 0.0 END) * 100, 1)
            AS call_right_pct
FROM silver.trades GROUP BY 1, 2;

CREATE OR REFRESH MATERIALIZED VIEW gold.shadow_scoreboard
COMMENT 'Every shadow on its latest day: family, trades, net, luck line and status (passed, above luck, watching, too early, kill).'
AS SELECT s.* FROM silver.shadow_status s
JOIN (SELECT max(day) AS day FROM silver.shadow_status) m ON s.day = m.day;

CREATE OR REFRESH MATERIALIZED VIEW gold.shadow_values
COMMENT 'Swing, long-term and benchmark shadow ledgers per day, with the gain against their starting pool.'
AS SELECT day, shadow,
          CASE WHEN shadow LIKE 'B%' THEN 'benchmark' WHEN shadow LIKE 'L%' THEN 'long-term' ELSE 'swing' END AS kind,
          capital, value, round(value - capital, 2) AS gain_rs, round((value / capital - 1) * 100, 2) AS gain_pct,
          holdings, closed_trades
FROM silver.shadow_ledgers;

CREATE OR REFRESH MATERIALIZED VIEW gold.deals_board
COMMENT 'NSE bulk and block deals of ₹1 crore and more in the last 30 days, biggest first within each day.'
AS SELECT day, kind, symbol, client, side, qty, price, round(value_rs / 1e7, 2) AS value_cr
FROM silver.deals WHERE value_rs >= 1e7 AND day >= date_sub(current_date(), 30);

CREATE OR REFRESH MATERIALIZED VIEW gold.data_freshness
COMMENT 'The newest day each source has reached, to spot a job that stopped.'
AS SELECT 'journal' AS source, max(trade_date) AS newest_day FROM silver.trade_events
UNION ALL SELECT 'pools', max(day) FROM silver.pool_days
UNION ALL SELECT 'shadow trades', max(day) FROM silver.shadow_trades
UNION ALL SELECT 'shadow status', max(day) FROM silver.shadow_status
UNION ALL SELECT 'shadow ledgers', max(day) FROM silver.shadow_ledgers
UNION ALL SELECT 'NSE bhavcopy', max(day) FROM silver.nse_eq_daily
UNION ALL SELECT 'NSE deals', max(day) FROM silver.deals
UNION ALL SELECT 'Telegram feed', to_date(max(sent_at)) FROM silver.feed;
