-- Every NSE stock on the latest trading day, with its 52-week high and low: sectors, breadth, Explore's lists.
WITH last AS (SELECT max(day) AS day FROM upx.silver.nse_eq_daily),
     year AS (SELECT symbol, max(high) AS hi52, min(low) AS lo52 FROM upx.silver.nse_eq_daily
              WHERE day > (SELECT date_sub(day, 365) FROM last) GROUP BY symbol)
SELECT e.day, e.symbol, e.close, e.prev_close, round((e.close / e.prev_close - 1) * 100, 2) AS change_pct,
       e.volume, round(e.turnover_rs / 1e7, 2) AS turnover_cr, e.deliv_pct, y.hi52, y.lo52
FROM upx.silver.nse_eq_daily e JOIN last USING (day) LEFT JOIN year y USING (symbol)
WHERE e.series = 'EQ' AND e.prev_close > 0
