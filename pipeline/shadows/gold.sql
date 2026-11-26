-- upx-shadows: the rule-based paper shadows (intraday trades, status and luck lines, swing and long-term
-- ledgers, NIFTYBEES benchmarks). Runs 17:30 IST, after the shadows job.
-- Gold: what the dashboard, the app and the reviews read.

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
