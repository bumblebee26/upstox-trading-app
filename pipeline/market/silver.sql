-- upx-market: NSE files (bhavcopy with delivery, deals, filings, results calendar) and the copied history.
-- Runs 20:05 IST, after the NSE evening job.
-- Silver: parsed, newest copy of each record kept.

CREATE OR REFRESH MATERIALIZED VIEW silver.nse_eq_daily
COMMENT 'NSE close, volume and delivery % per stock and day (delivery bhavcopy).'
AS SELECT * EXCEPT (rn) FROM (
  SELECT to_date(v:day::string) AS day, v:symbol::string AS symbol, 'EQ' AS series,
         v:open::double AS open, v:high::double AS high, v:low::double AS low, v:close::double AS close,
         v:prev_close::double AS prev_close, v:volume::bigint AS volume,
         v:turnover_lacs::double * 1e5 AS turnover_rs, v:deliv_qty::bigint AS deliv_qty,
         v:deliv_pct::double AS deliv_pct, 'nse_daily' AS source,
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
