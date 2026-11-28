-- Every reviewed intraday trade of the last 90 days that closed: the council's and the AI's YES % against the result.
WITH r AS (SELECT review_id, raw:agent_yes_pct::double AS ai_yes_pct, raw:council.yes_pct::double AS council_yes_pct
           FROM upx.silver.trade_events WHERE event = 'review' AND trade_date >= date_sub(current_date(), 90)),
     x AS (SELECT review_id, net_rs FROM upx.silver.trade_events WHERE event = 'exit' AND review_id IS NOT NULL)
SELECT r.review_id, r.ai_yes_pct, r.council_yes_pct, x.net_rs FROM r JOIN x USING (review_id)
