-- upx-trading: the real pools (journals, balances) and the Telegram feed. Runs 13:05 and 16:55 IST.
-- Silver: parsed, newest copy of each record kept.

CREATE OR REFRESH MATERIALIZED VIEW silver.trade_events
COMMENT 'Every journal event once (the newest copy per event_id): reviews, fills, exits, stops, ratings, blocks, decisions.'
AS SELECT * EXCEPT (rn) FROM (
  SELECT
    v:event_id::string AS event_id,
    v:event::string AS event,
    coalesce(v:pool::string, 'intraday') AS pool,
    to_date(regexp_extract(_source_file, '([0-9]{4}-[0-9]{2}-[0-9]{2})', 1)) AS trade_date,
    v:written_at::string AS written_at,
    v:at::string AS at_ist,
    v:symbol::string AS symbol,
    v:side::string AS side,
    v:setup::string AS setup,
    v:qty::int AS qty,
    v:price::double AS price,
    v:net_rs::double AS net_rs,
    v:charges_rs::double AS charges_rs,
    v:reason::string AS reason,
    v:review_id::string AS review_id,
    v:rating::string AS rating,
    v AS raw,
    _file_modified_at,
    row_number() OVER (PARTITION BY v:event_id::string ORDER BY _file_modified_at DESC) AS rn
  FROM (SELECT try_parse_json(line) AS v, _source_file, _file_modified_at FROM bronze.journal_raw)
  WHERE v IS NOT NULL AND v:event_id IS NOT NULL
) WHERE rn = 1;

CREATE OR REFRESH MATERIALIZED VIEW silver.trades
COMMENT 'Closed trades of the real pools: one row per exit, with its setup and the 👍/👎 of the owner when there is one.'
AS WITH reviews AS (
  SELECT review_id, any_value(setup) AS setup FROM silver.trade_events WHERE event = 'review' GROUP BY review_id
), ratings AS (
  SELECT review_id, max_by(rating, written_at) AS rating FROM silver.trade_events WHERE event = 'rating' GROUP BY review_id
)
SELECT x.trade_date, x.pool, x.symbol, x.qty, x.price AS exit_price, x.net_rs, x.charges_rs, x.reason AS exit_reason,
       x.review_id, coalesce(r.setup, 'not recorded') AS setup, g.rating, x.net_rs > 0 AS won, x.written_at
FROM silver.trade_events x
LEFT JOIN reviews r ON x.review_id = r.review_id
LEFT JOIN ratings g ON x.review_id = g.review_id
WHERE x.event = 'exit';

CREATE OR REFRESH MATERIALIZED VIEW silver.pool_days
COMMENT 'The balance of each real pool at the end of each day (the newest saved copy).'
AS SELECT * EXCEPT (rn) FROM (
  SELECT to_date(v:day::string) AS day, v:pool::string AS pool, v:balance::double AS balance,
         v:starting_capital::double AS starting_capital, v:realized_today::double AS realized_today,
         v:open_positions::int AS open_positions,
         row_number() OVER (PARTITION BY v:day::string, v:pool::string ORDER BY _file_modified_at DESC) AS rn
  FROM (SELECT try_parse_json(line) AS v, _file_modified_at FROM bronze.pools_raw) WHERE v IS NOT NULL
) WHERE rn = 1;

CREATE OR REFRESH MATERIALIZED VIEW silver.feed
COMMENT 'Every Telegram message the system sent (the Feed tab of the app).'
AS SELECT * EXCEPT (rn) FROM (
  SELECT try_to_timestamp(v:ts::string) AS sent_at, v:id::bigint AS message_id, v:text::string AS text,
         v:reply_to::bigint AS reply_to,
         row_number() OVER (PARTITION BY v:id::bigint ORDER BY _file_modified_at DESC) AS rn
  FROM (SELECT try_parse_json(line) AS v, _file_modified_at FROM bronze.feed_raw) WHERE v IS NOT NULL
) WHERE rn = 1;
