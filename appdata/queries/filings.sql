-- NSE filings of the last 3 days (Explore's "In the news").
SELECT symbol, filed_at, what, detail, link FROM upx.silver.filings
WHERE filed_at >= date_sub(current_date(), 3) ORDER BY filed_at DESC
