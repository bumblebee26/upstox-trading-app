-- All-time results by pool and setup.
SELECT pool, setup, trades, win_pct, net_rs, first_day, last_day FROM upx.gold.trading_by_setup ORDER BY trades DESC
