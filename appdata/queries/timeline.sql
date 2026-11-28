-- Who took how long on each trade (last 90 days).
SELECT trade_date, pool, symbol, review_id, net_rs, facts_s, ai_decide_s, council_s, approval, approval_s,
       placing_s, fill_s, hold_min, total_min
FROM upx.gold.trade_timeline WHERE trade_date >= date_sub(current_date(), 90)
