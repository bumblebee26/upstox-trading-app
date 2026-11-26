-- upx-shadows: the rule-based paper shadows (intraday trades, status and luck lines, swing and long-term
-- ledgers, NIFTYBEES benchmarks). Runs 17:30 IST, after the shadows job.
-- Silver: parsed, newest copy of each record kept.

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
