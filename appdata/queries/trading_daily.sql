-- Each real pool per day: trades, wins, net after charges (last 400 days).
SELECT day, pool, trades, wins, net_rs, charges_rs, balance
FROM upx.gold.trading_daily WHERE day >= date_sub(current_date(), 400) ORDER BY day
