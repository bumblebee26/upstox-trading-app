-- Silver: the bronze lines parsed (VARIANT), with only the newest copy of each record kept (a rewritten file
-- brings its lines again). Dummy-money paper trader.

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

CREATE OR REFRESH MATERIALIZED VIEW silver.shadow_trades
COMMENT 'Intraday shadow trades (paper, rule-based), one per variant, stock and entry time.'
AS SELECT * EXCEPT (rn) FROM (
  SELECT to_date(v:day::string) AS day, v:variant::string AS variant, v:symbol::string AS symbol,
         v:side::string AS side, v:entry_time::string AS entry_time, v:entry::double AS entry,
         v:exit_time::string AS exit_time, v:exit::double AS exit_price, v:exit_reason::string AS exit_reason,
         v:qty::int AS qty, v:charges_rs::double AS charges_rs, v:net_rs::double AS net_rs, v:r::double AS r,
         row_number() OVER (PARTITION BY v:day::string, v:variant::string, v:symbol::string, v:entry_time::string
                            ORDER BY _file_modified_at DESC) AS rn
  FROM (SELECT try_parse_json(line) AS v, _file_modified_at FROM bronze.shadow_trades_raw) WHERE v IS NOT NULL
) WHERE rn = 1;

CREATE OR REFRESH MATERIALIZED VIEW silver.shadow_status
COMMENT 'Family, trades, net result, luck line and status of each shadow, per day.'
AS SELECT * EXCEPT (rn) FROM (
  SELECT to_date(v:day::string) AS day, v:variant::string AS variant, v:family::string AS family,
         v:trades::int AS trades, v:net_rs::double AS net_rs, v:avg_trade_rs::double AS avg_trade_rs,
         v:luck_line::double AS luck_line, v:status::string AS status,
         row_number() OVER (PARTITION BY v:day::string, v:variant::string ORDER BY _file_modified_at DESC) AS rn
  FROM (SELECT try_parse_json(line) AS v, _file_modified_at FROM bronze.shadow_status_raw) WHERE v IS NOT NULL
) WHERE rn = 1;

CREATE OR REFRESH MATERIALIZED VIEW silver.shadow_ledgers
COMMENT 'Value of each swing, long-term and NIFTYBEES benchmark shadow ledger, per day.'
AS SELECT * EXCEPT (rn) FROM (
  SELECT to_date(v:day::string) AS day, v:id::string AS shadow, v:capital::double AS capital, v:cash::double AS cash,
         v:value::double AS value, v:holdings::int AS holdings, v:closed::int AS closed_trades,
         row_number() OVER (PARTITION BY v:day::string, v:id::string ORDER BY _file_modified_at DESC) AS rn
  FROM (SELECT try_parse_json(line) AS v, _file_modified_at FROM bronze.shadow_ledgers_raw) WHERE v IS NOT NULL
) WHERE rn = 1;

CREATE OR REFRESH MATERIALIZED VIEW silver.nse_eq_daily
COMMENT 'NSE close, volume and delivery % per stock and day (delivery bhavcopy).'
AS SELECT * EXCEPT (rn) FROM (
  SELECT to_date(v:day::string) AS day, v:symbol::string AS symbol, v:close::double AS close,
         v:volume::bigint AS volume, v:deliv_qty::bigint AS deliv_qty, v:deliv_pct::double AS deliv_pct,
         row_number() OVER (PARTITION BY v:day::string, v:symbol::string ORDER BY _file_modified_at DESC) AS rn
  FROM (SELECT try_parse_json(line) AS v, _file_modified_at FROM bronze.nse_bhav_raw) WHERE v IS NOT NULL
) WHERE rn = 1;

CREATE OR REFRESH MATERIALIZED VIEW silver.deals
COMMENT 'NSE bulk and block deals, each once.'
AS SELECT DISTINCT to_date(v:day::string) AS day, v:kind::string AS kind, v:symbol::string AS symbol,
       v:client::string AS client, v:side::string AS side, v:qty::bigint AS qty, v:price::double AS price,
       v:qty::double * v:price::double AS value_rs
FROM (SELECT try_parse_json(line) AS v FROM bronze.nse_deals_raw) WHERE v IS NOT NULL AND v:day IS NOT NULL;

CREATE OR REFRESH MATERIALIZED VIEW silver.filings
COMMENT 'NSE company filings (announcements), each once.'
AS SELECT DISTINCT v:symbol::string AS symbol, try_to_timestamp(v:an_dt::string, 'dd-MMM-yyyy HH:mm:ss') AS filed_at,
       v:desc::string AS what, left(v:attchmntText::string, 500) AS detail, v:attchmntFile::string AS link
FROM (SELECT try_parse_json(line) AS v FROM bronze.nse_filings_raw) WHERE v IS NOT NULL AND v:symbol IS NOT NULL;

CREATE OR REFRESH MATERIALIZED VIEW silver.board_meetings
COMMENT 'NSE board meetings (results and others), as last seen in the calendar.'
AS SELECT v:symbol::string AS symbol, to_date(v:day::string) AS day, v:purpose::string AS purpose,
       max(to_date(v:saved_on::string)) AS last_seen
FROM (SELECT try_parse_json(line) AS v FROM bronze.nse_calendar_raw) WHERE v IS NOT NULL AND v:day IS NOT NULL
GROUP BY 1, 2, 3;

CREATE OR REFRESH MATERIALIZED VIEW silver.feed
COMMENT 'Every Telegram message the system sent (the Feed tab of the app).'
AS SELECT * EXCEPT (rn) FROM (
  SELECT try_to_timestamp(v:ts::string) AS sent_at, v:id::bigint AS message_id, v:text::string AS text,
         v:reply_to::bigint AS reply_to,
         row_number() OVER (PARTITION BY v:id::bigint ORDER BY _file_modified_at DESC) AS rn
  FROM (SELECT try_parse_json(line) AS v, _file_modified_at FROM bronze.feed_raw) WHERE v IS NOT NULL
) WHERE rn = 1;
