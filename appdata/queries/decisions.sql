-- What the AI did on the last 5 trading days: reviews, placed trades, skips, passes and exits, newest first.
SELECT trade_date, pool, event, at_ist, written_at, symbol, side, setup, qty, price, net_rs, reason, review_id,
       raw:score::double AS score, raw:council.yes_pct::double AS council_yes_pct
FROM upx.silver.trade_events
WHERE event IN ('review', 'placed', 'fill', 'skipped', 'pass', 'not_approved', 'exit')
  AND trade_date >= (SELECT date_sub(max(trade_date), 7) FROM upx.silver.trade_events)
ORDER BY written_at DESC
