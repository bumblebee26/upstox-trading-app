-- Intraday shadows' net per day (last 400 days): the real vs shadows chart and Rules compared.
SELECT day, variant, sum(net_rs) AS net_rs, count(*) AS trades
FROM upx.silver.shadow_trades WHERE day >= date_sub(current_date(), 400) GROUP BY day, variant ORDER BY day
