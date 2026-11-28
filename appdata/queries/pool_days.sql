-- Each real pool's balance per day (last 400 days): the P&L blocks, Each pool and the P&L charts.
SELECT day, pool, balance, starting_capital, realized_today, open_positions
FROM upx.silver.pool_days WHERE day >= date_sub(current_date(), 400) ORDER BY day
