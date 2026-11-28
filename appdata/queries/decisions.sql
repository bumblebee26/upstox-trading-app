-- What the AI did on the last 7 days: screens, reviews, fills, skips, passes, exits and the pools' decisions,
-- newest first. Reviews carry entry, stop, target and both YES % (the AI's own and the council's).
SELECT trade_date, pool, event, at_ist, written_at, symbol, side, setup, qty, price, net_rs, reason, review_id,
       raw:agent_yes_pct::double AS ai_yes_pct, raw:council.yes_pct::double AS council_yes_pct,
       raw:entry::double AS entry, raw:stop::double AS stop, raw:target::double AS target, raw:rr::double AS rr,
       raw:why::string AS why, to_json(raw:top) AS top, to_json(raw:final) AS final, to_json(raw:context.candidates) AS candidates
FROM upx.silver.trade_events
WHERE event IN ('screen', 'review', 'placed', 'fill', 'skipped', 'pass', 'not_approved', 'exit', 'decision')
  AND trade_date >= (SELECT date_sub(max(trade_date), 7) FROM upx.silver.trade_events)
ORDER BY written_at DESC
