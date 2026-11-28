-- Closed real trades of the last 90 days, newest first: win rate, average R, profit factor and Today's trades.
SELECT trade_date, pool, symbol, qty, exit_price, net_rs, charges_rs, exit_reason, review_id, setup, rating, won
FROM upx.silver.trades WHERE trade_date >= date_sub(current_date(), 90) ORDER BY written_at DESC
